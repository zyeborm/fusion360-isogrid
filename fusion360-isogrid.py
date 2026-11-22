"""Fusion 360 Isogrid: planar isogrid pocket finishing feature for Autodesk Fusion.

Entry points: run(context), stop(context). Autodesk Fusion's bundled Python is
required; this module is intentionally not imported by the standalone tests.
"""
import adsk.core
import adsk.fusion
import json
import math
import os
import sys
import importlib
import traceback
import time
import html
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import geometry
import fitting
import fast_fit
import async_engine
import curves2d as exact_curves
import exact_clipper
import update_checker
import preview_timing
import manufacturability
import presets
import saved_mass
import tool_center
from offset_cleanup import OffsetInterval

APP = adsk.core.Application.get()
UI = APP.userInterface
COMMAND_ID = 'fusion360_isogrid_create'
COMMAND_NAME = 'fusion360-isogrid'
# Keep the version in the running Python code, not in the on-disk manifest:
# the updater replaces that manifest while this old code remains loaded.
RUNNING_VERSION = '0.8.8'
COMMAND_TITLE = f'{COMMAND_NAME} v{RUNNING_VERSION}'
PANEL_ID = 'SolidScriptsAddinsPanel'
WORKSPACE_ID = 'FusionSolidEnvironment'
ATTRIBUTE_GROUP = 'fusion360-isogrid'
CUSTOM_EVENT_ID = 'fusion360_isogrid_worker_9b70f5e1'
_handlers = []
_sessions = []
_custom_event = None
_update_checker = None
_update_installer = None


def _show_update_notice(session):
    """Sync update notice/button from worker state on Fusion's UI thread."""
    if not session.alive or session.inputs is None or _update_checker is None:
        return
    notice = session.inputs.itemById('update_notice')
    button = session.inputs.itemById('install_update')
    if notice is None or button is None:
        return
    newer = _update_checker.available()
    manual_status = _update_checker.manual_status()
    state = (_update_installer.state() if _update_installer is not None
             else ('idle', None, None))
    token = (newer, state, manual_status)
    if getattr(session, '_shown_update', None) == token:
        return
    session._shown_update = token
    status, version, error = state
    if status == 'installed':
        notice.formattedText = (
            f'<b>Installed v{html.escape(version)}.</b> '
            f'Currently running v{html.escape(RUNNING_VERSION)}. '
            'Restart Fusion to activate the update.')
        notice.isVisible = True
        button.isVisible = False
    elif status == 'working':
        notice.formattedText = (
            f'Installing v{html.escape(version)}… '
            f'(running v{html.escape(RUNNING_VERSION)})')
        notice.isVisible = True
        button.isVisible = False
    elif manual_status[0] == 'checking':
        notice.formattedText = 'Checking GitHub for updates…'
        notice.isVisible = True
        button.isVisible = False
    elif newer:
        detail = (f'Previous installation attempt failed: {html.escape(error)}. '
                  if status == 'error' and error else '')
        notice.formattedText = (detail +
            f'<b>Update v{html.escape(newer)} available</b> '
            f'(running v{html.escape(RUNNING_VERSION)}). '
            'Install directly from GitHub?')
        notice.isVisible = True
        button.isVisible = True
    elif manual_status[0] == 'current':
        notice.formattedText = (
            f'Up to date — currently running v{html.escape(RUNNING_VERSION)}.')
        notice.isVisible = True
        button.isVisible = False
    elif manual_status[0] == 'error':
        notice.formattedText = (
            f'Update check failed: {html.escape(str(manual_status[1]))}. '
            'Use Check for Updates to retry.')
        notice.isVisible = True
        button.isVisible = False
    else:
        notice.isVisible = False
        button.isVisible = False


# Geometric warnings remain advisory. Fusion may disable OK when its native
# isValueError state is set, even if validateInputs returns True. We leave that
# flag clear and report issues with field tooltips and a warnings text area.
# Text is still evaluated through Fusion's UnitsManager to preserve units,
# expressions, and user parameters.
ADVISORY_INPUT_UNITS = {
    'pitch': 'mm', 'rib': 'mm', 'perimeter': 'mm', 'holeclear': 'mm',
    'corner': 'mm', 'nodehole': 'mm', 'minfraction': '',
    'fit_min_pitch': 'mm', 'fit_max_pitch': 'mm',
    'tool_diameter': 'mm',
}


def _units_manager():
    design = adsk.fusion.Design.cast(APP.activeProduct)
    if design is None:
        raise ValueError('Open a Fusion design to evaluate dimensional expressions.')
    return design.unitsManager


def _input_number(inputs, key, units=None):
    field = inputs.itemById(key)
    if key not in ADVISORY_INPUT_UNITS:
        return field.value
    if units is None:
        units = _units_manager()
    unit_type = ADVISORY_INPUT_UNITS[key]
    try:
        if key == 'minfraction':
            # A blank unit type means the *document's length units* in Fusion.
            # Multiply a unitless expression by 1 mm to enforce dimensional
            # consistency, then convert the resulting internal cm to a scalar.
            expression = f'({field.value}) * 1 mm'
            if not units.isValidExpression(expression, 'mm'):
                raise ValueError('invalid unitless expression')
            return 10.0 * units.evaluateExpression(expression, 'mm')
        if not units.isValidExpression(field.value, unit_type):
            raise ValueError('invalid dimensional expression')
        return units.evaluateExpression(field.value, unit_type)
    except Exception as exc:
        raise ValueError(f'{field.name}: invalid expression ({field.value}).') from exc


def _input_expression(inputs, key):
    field = inputs.itemById(key)
    return field.value if key in ADVISORY_INPUT_UNITS else field.expression


def _set_input_number(inputs, key, internal_value):
    """Set an optimiser result without changing a user's display-unit choices."""
    field = inputs.itemById(key)
    if key in ADVISORY_INPUT_UNITS:
        units = _units_manager()
        field.value = units.formatInternalValue(
            internal_value, ADVISORY_INPUT_UNITS[key], True)
    else:
        field.value = internal_value


def _preset_input(inputs,key):
    """Resolve nested preset controls through their GroupCommandInput.

    Fusion's CommandInputs.itemById is scoped to one parent collection;
    nested group members are not available from the root collection.
    """
    try:
        group=inputs.itemById('preset_group')
    except KeyError:
        group=None  # Flat test doubles have no nested GroupCommandInput.
    if group is not None:
        children=group.children
        if key.startswith('preset_include_'):
            return children.itemById('preset_fields_group').children.itemById(key)
        return children.itemById(key)
    return inputs.itemById(key)


def _preset_field_value(inputs,key):
    field=inputs.itemById(key)
    if key in presets.EXPRESSION_FIELDS:
        return _input_expression(inputs,key)
    if key in presets.BOOL_FIELDS:
        return bool(field.value)
    return field.selectedItem.name


def _set_preset_field(inputs,key,value):
    field=inputs.itemById(key)
    if key in presets.EXPRESSION_FIELDS:
        if key in ADVISORY_INPUT_UNITS:
            field.value=value
        else:
            field.expression=value
    elif key in presets.BOOL_FIELDS:
        field.value=value
    else:
        item=field.listItems.itemByName(value)
        if item is None:
            raise ValueError('Preset refers to unavailable option: '+str(value))
        item.isSelected=True


def _refresh_preset_choices(inputs,store,selected=None):
    field=_preset_input(inputs,'preset_choice')
    field.listItems.clear()
    field.listItems.add('— Choose saved preset —', selected is None)
    for name in store.names():
        field.listItems.add(name,name==selected)


def _set_preset_inclusions(inputs,names):
    included=set(names)
    for key in presets.FIELDS:
        _preset_input(inputs,'preset_include_'+key).value=key in included


def _included_preset_values(inputs):
    return {key:_preset_field_value(inputs,key) for key in presets.FIELDS
            if _preset_input(inputs,'preset_include_'+key).value}


def _auto_vertex_hole(inputs):
    """Set a vertex-hole diameter preserving rib-width material at each pocket.

    All dimensions are Fusion internal centimetres. Reuse the same geometric
    limit as the field advisories and preserve expression/unit formatting.
    This is an action, not a persistent automatic mode: users can edit the
    resulting diameter independently afterward.
    """
    units = _units_manager()
    rib = _input_number(inputs, 'rib', units)
    radius = _input_number(inputs, 'corner', units)
    if rib<=0 or radius<0:
        raise ValueError('Auto hole size requires a positive rib width and a non-negative corner radius.')
    maximum = geometry.maximum_vertex_hole_diameter(rib, radius)
    _set_input_number(inputs, 'nodehole', maximum)
    return maximum


def _p(x, y, z): return adsk.core.Point3D.create(x, y, z)
def _v(x, y, z): return adsk.core.Vector3D.create(x, y, z)


class FaceFrame:
    """Stable face-local coordinate system in the selected component's space."""
    def __init__(self, face):
        self.origin = face.pointOnFace
        ok, normal = face.evaluator.getNormalAtPoint(self.origin)
        if not ok: raise ValueError('Could not evaluate the selected face normal.')
        self.n = normal.copy(); self.n.normalize()
        x = _v(1, 0, 0) if abs(self.n.x) < 0.9 else _v(0, 1, 0)
        d = x.dotProduct(self.n)
        x.subtract(_v(self.n.x*d, self.n.y*d, self.n.z*d));x.normalize()
        self.x=x
        self.y=self.n.crossProduct(x);self.y.normalize()

    def to_xy(self, point):
        d=self.origin.vectorTo(point)
        return (d.dotProduct(self.x), d.dotProduct(self.y))

    def to_world(self, point, lift=0.0):
        a,b=point
        return _p(self.origin.x+self.x.x*a+self.y.x*b+self.n.x*lift,
                  self.origin.y+self.x.y*a+self.y.y*b+self.n.y*lift,
                  self.origin.z+self.x.z*a+self.y.z*b+self.n.z*lift)


def _strokes(curve_eval,tolerance):
    good,a,b=curve_eval.getParameterExtents()
    if not good: raise ValueError('Failed to read a boundary curve.')
    good, pts=curve_eval.getStrokes(a,b,tolerance)
    if not good or len(pts)<2:
        good, pts=curve_eval.getEndPoints()
        if not good: raise ValueError('Failed to sample a boundary curve.')
    return list(pts)


def _sequence(samples,frame):
    """Join B-Rep coedges or profile curves into a closed polygon.

    Fusion exposes ordered coedges; a local orientation choice is still needed
    because the BRep edge's parameter direction can oppose its coedge direction.
    """
    pieces=[[frame.to_xy(p) for p in points] for points in samples]
    if not pieces:return []
    # Orient the first piece toward the next piece's nearer endpoint.
    if len(pieces)>1:
        a=pieces[0];b=pieces[1]
        if min(geometry.norm(geometry.sub(a[0],b[0])),geometry.norm(geometry.sub(a[0],b[-1]))) < min(
               geometry.norm(geometry.sub(a[-1],b[0])),geometry.norm(geometry.sub(a[-1],b[-1]))):
            a.reverse()
    chain=list(pieces[0])
    for pts in pieces[1:]:
        if geometry.norm(geometry.sub(chain[-1],pts[0])) > geometry.norm(geometry.sub(chain[-1],pts[-1])):
            pts.reverse()
        if geometry.norm(geometry.sub(chain[-1],pts[0]))>0.02:
            raise ValueError('Boundary curves do not form a continuous chain.')
        chain.extend(pts[1:])
    if len(chain)>2 and geometry.norm(geometry.sub(chain[0],chain[-1]))>0.02:
        raise ValueError('Boundary is open; select a closed face/profile.')
    return geometry.clean(chain)


def _analytic_curve(curve,evaluator,frame,tolerance):
    """Extract bounded Fusion curves without converting smooth edges into lines.

    Everything returned is plain Python, including NURBS control points and
    trims. This is essential for the background calculation thread.
    """
    kind=curve.objectType
    def matches(name):
        cls=getattr(adsk.core,name,None)
        return cls is not None and kind==cls.classType()
    is_line=matches('Line3D')
    is_circle=matches('Arc3D') or matches('Circle3D')
    is_ellipse=matches('Ellipse3D') or matches('EllipticalArc3D')
    is_nurbs=matches('NurbsCurve3D')
    if matches('Polyline3D'):
        points=[frame.to_xy(pt) for pt in curve.points]
        return [exact_curves.Line(a,b) for a,b in zip(points,points[1:])
                if exact_curves.length(exact_curves.sub(a,b))>1e-9]
    if not (is_line or is_circle or is_ellipse or is_nurbs):
        # Fusion sketch conics are exposed as NURBS through worldGeometry;
        # any other bounded Curve3D is converted to NURBS if supported.
        converted=getattr(curve,'asNurbsCurve',None)
        if converted is not None and converted is not curve:
            return _analytic_curve(converted,evaluator,frame,tolerance)
        # Unknown future Fusion curve type: conservative compatibility path.
        points=[frame.to_xy(pt) for pt in _strokes(evaluator,tolerance)]
        return [exact_curves.Line(a,b) for a,b in zip(points,points[1:])
                if exact_curves.length(exact_curves.sub(a,b))>1e-9]
    ok,t0,t1=evaluator.getParameterExtents()
    if not ok:raise ValueError('Failed to read curve parameter extents.')
    ok,p0=evaluator.getPointAtParameter(t0)
    valid,p1=evaluator.getPointAtParameter(t1)
    if not ok or not valid:raise ValueError('Failed to evaluate boundary endpoints.')
    a,b=frame.to_xy(p0),frame.to_xy(p1)
    if is_line:return [exact_curves.Line(a,b)]
    if is_nurbs:
        success,control,degree,knots,is_rational,weights,is_periodic=curve.getData()
        if not success:raise ValueError('Could not read Fusion NURBS definition.')
        controls=tuple(frame.to_xy(pt) for pt in control)
        weight_values=tuple(float(w) for w in weights) if is_rational else (1.,)*len(controls)
        return [exact_curves.Nurbs(controls,int(degree),tuple(float(k) for k in knots),
                                   weight_values,float(t0),float(t1),bool(is_periodic))]
    center=frame.to_xy(curve.center)
    if is_ellipse:
        ma=curve.majorAxis.copy();ma.normalize();ma.scaleBy(curve.majorRadius)
        minor=curve.normal.crossProduct(curve.majorAxis);minor.normalize()
        minor.scaleBy(curve.minorRadius)
        # Project the axis vectors into face coordinates, retaining their
        # handedness even when the sketch plane normal faces the other way.
        ma_point=curve.center.copy();ma_point.translateBy(ma)
        mi_point=curve.center.copy();mi_point.translateBy(minor)
        major=exact_curves.sub(frame.to_xy(ma_point),center)
        minor_axis=exact_curves.sub(frame.to_xy(mi_point),center)
        det=exact_curves.cross(major,minor_axis)
        if abs(det)<1e-12:raise ValueError('Degenerate elliptical boundary')
        def angle(p):
            vec=exact_curves.sub(p,center)
            return math.atan2(exact_curves.cross(major,vec)/det,
                              exact_curves.cross(vec,minor_axis)/det)
        theta0=angle(a);theta1=angle(b)
        ok,pm=evaluator.getPointAtParameter((t0+t1)/2)
        if not ok:raise ValueError('Could not determine ellipse traversal.')
        thetam=angle(frame.to_xy(pm))
        forward=(theta1-theta0)%math.tau
        halfway=(thetam-theta0)%math.tau
        if exact_curves.near(a,b,1e-6):
            ok,pq=evaluator.getPointAtParameter(t0+.25*(t1-t0))
            if not ok:raise ValueError('Could not determine full ellipse direction.')
            quarter=(angle(frame.to_xy(pq))-theta0)%math.tau
            sweep=math.tau if quarter<math.pi else -math.tau
        else:
            sweep=forward if halfway<forward else -(math.tau-forward)
        return [exact_curves.Ellipse(center,major,minor_axis,theta0,sweep)]
    # Exact circle / circular arc; the evaluator determines reversed edge
    # directions, full circles and sweeps spanning more than 180 degrees.
    ok,pm=evaluator.getPointAtParameter((t0+t1)/2)
    if not ok:raise ValueError('Failed to evaluate circular boundary midpoint.')
    m=frame.to_xy(pm)
    if exact_curves.near(a,b,1e-6):
        ok,pq=evaluator.getPointAtParameter(t0+(t1-t0)/4)
        if not ok:raise ValueError('Failed to determine full-circle direction.')
        q=frame.to_xy(pq)
        sign=1 if exact_curves.cross(exact_curves.sub(a,center),
                                    exact_curves.sub(q,center))>0 else -1
        return [exact_curves.Arc(center,a,a,sign*math.tau)]
    theta0=math.atan2(a[1]-center[1],a[0]-center[0])
    thetam=math.atan2(m[1]-center[1],m[0]-center[0])
    theta1=math.atan2(b[1]-center[1],b[0]-center[0])
    forward=(theta1-theta0)%math.tau
    halfway=(thetam-theta0)%math.tau
    sweep=forward if halfway<forward else -(math.tau-forward)
    return [exact_curves.Arc(center,a,b,sweep)]


def _curve_chain(pieces,outer):
    """Orient native coedges to form one topological loop."""
    pieces=[list(part) for part in pieces if part]
    if not pieces:return []
    if len(pieces)==1 and len(pieces[0])==1:
        seg=pieces[0][0]
        if isinstance(seg,(exact_curves.Arc,exact_curves.Ellipse)) and abs(seg.sweep)>math.tau-1e-7:
            return [seg if (exact_curves.loop_area([seg])>0)==outer else seg.reverse()]
        if exact_curves.near(seg.start,seg.end) and exact_curves.close_loop([seg]):
            return [seg if (exact_curves.loop_area([seg])>0)==outer else seg.reverse()]
    if len(pieces)>1:
        first,second=pieces[:2]
        if min(exact_curves.length(exact_curves.sub(first[0].start,second[0].start)),
               exact_curves.length(exact_curves.sub(first[0].start,second[-1].end))) < min(
               exact_curves.length(exact_curves.sub(first[-1].end,second[0].start)),
               exact_curves.length(exact_curves.sub(first[-1].end,second[-1].end))):
            pieces[0]=exact_curves.reverse_loop(first)
    chain=pieces[0]
    for item in pieces[1:]:
        if exact_curves.length(exact_curves.sub(chain[-1].end,item[0].start)) > exact_curves.length(exact_curves.sub(chain[-1].end,item[-1].end)):
            item=exact_curves.reverse_loop(item)
        if not exact_curves.near(chain[-1].end,item[0].start,1e-4):
            raise ValueError('Input boundary curves do not connect.')
        chain.extend(item)
    if not exact_curves.close_loop(chain,1e-4):
        raise ValueError('Input curve boundary is open.')
    if (exact_curves.loop_area(chain)>0)!=outer:
        chain=exact_curves.reverse_loop(chain)
    return chain


def _face_region(face,frame,tolerance):
    loops=[]
    curve_loops=[]
    for i in range(face.loops.count):
        loop=face.loops.item(i)
        parts=[]
        for k in range(loop.coEdges.count):
            edge=loop.coEdges.item(k).edge
            parts.append(_analytic_curve(edge.geometry,edge.evaluator,frame,tolerance))
        path=_curve_chain(parts,bool(loop.isOuter))
        curve_loops.append(path)
        loops.append((exact_curves.sample(path,tolerance),bool(loop.isOuter)))
    return geometry.Region(loops,curve_loops=curve_loops)


def _profile_region(profile,frame,tolerance):
    loops=[]
    curve_loops=[]
    for i in range(profile.profileLoops.count):
        loop=profile.profileLoops.item(i)
        parts=[]
        for j in range(loop.profileCurves.count):
            ent=loop.profileCurves.item(j).sketchEntity
            curve=ent.worldGeometry
            parts.append(_analytic_curve(curve,curve.evaluator,frame,tolerance))
        path=_curve_chain(parts,bool(loop.isOuter))
        curve_loops.append(path)
        loops.append((exact_curves.sample(path,tolerance),bool(loop.isOuter)))
    return geometry.Region(loops,curve_loops=curve_loops)


def _inputs_to_settings(inputs):
    ids=('pitch','rib','depth','perimeter','holeclear','dx','dy','angle',
         'corner','nodehole','minfraction','tool_diameter')
    units = _units_manager()
    settings={key:_input_number(inputs,key,units) for key in ids}
    settings['depth_expression']=_input_expression(inputs,'depth')
    settings['trim_boundary']=inputs.itemById('trim_boundary').value
    for key in ('origin_mode','anchor','alignment'):
        selected=inputs.itemById(key).selectedItem
        settings[key]=selected.name if selected else ''
    # Optional GEOS backend selector disabled until compiled-wheel safety is resolved.
    # settings['backend']={'Automatic':'auto',
    #                      'Pure Python':'python',
    #                      'GEOS accelerated':'geos'}[settings['backend_choice']]
    settings['backend']='python'
    return settings


def _selected_density(inputs):
    item=inputs.itemById('material_density').selectedItem
    material=item.name if item else 'Aluminium'
    custom=inputs.itemById('custom_density').value if material=='User' else None
    return saved_mass.density(material,custom)


def _selected(inputs):
    field=inputs.itemById('face')
    if field.selectionCount!=1: raise ValueError('Select one planar face.')
    face=field.selection(0).entity
    # Work in a component's native coordinate system, rather than mixing a
    # selected occurrence proxy with a native sketch and extrusion.
    if face.nativeObject: face=face.nativeObject
    if not face.body.isSolid: raise ValueError('Select a face on a solid body.')
    mask_input=inputs.itemById('mask')
    profile=mask_input.selection(0).entity if mask_input.selectionCount else None
    if profile and profile.nativeObject: profile=profile.nativeObject
    if profile and profile.parentSketch.parentComponent != face.body.parentComponent:
        raise ValueError('The bounding sketch profile must be in the same component as the face.')
    return face,profile


def _validate_settings(s):
    if s['pitch']<=0 or s['rib']<=0 or s['rib']>=s['pitch']/geometry.SQRT3:
        raise ValueError('Cell pitch must be greater than 1.732 × rib width.')
    if s['depth']<=0:raise ValueError('Extrusion depth must be positive.')
    if min(s[k] for k in ('perimeter','holeclear','corner','nodehole'))<0:
        raise ValueError('Margins, corner radius and vertex hole diameter must be non-negative.')
    if s['tool_diameter']<0:
        raise ValueError('Cutter diameter must be non-negative; 0 disables tool checks.')
    # Oversized corner radii are advisory: the geometry engine keeps the
    # pockets and reports any corners it cannot round at the given radius.
    # A large vertex hole may merge with triangular cuts. Warn in the dialog,
    # but leave this choice to the user rather than applying an arbitrary cap.
    if not 0<=s['minfraction']<=100:
        raise ValueError('Minimum retained area must be 0–100%.')


def _geometry_warnings(s, outlines=None):
    """Non-blocking design advisories, expressed in source-field units (cm).

    Warnings remain advisory and never affect Fusion's OK button.
    """
    messages=[]
    pitch=s['pitch'];rib=s['rib'];corner=s['corner'];hole=s['nodehole']
    tool=s.get('tool_diameter',0.)
    if tool<0:messages.append('Cutter diameter must be non-negative; 0 disables cutter checks.')
    if tool>0 and corner+1e-9<tool/2:
        messages.append(f'Pocket corner radius {corner*10:.3g} mm is smaller than '
                        f'cutter radius {tool*5:.3g} mm; inspect machining feasibility.')
    if pitch<=0:messages.append('Cell pitch must be positive for a cut.')
    if rib<=0:messages.append('Rib width must be positive for a cut.')
    if pitch>0 and rib>=pitch/geometry.SQRT3:
        messages.append('Rib width is too large relative to Cell pitch; no triangular pocket can form.')
    if pitch>geometry.SQRT3*rib and corner>0:
        maximum=(pitch-geometry.SQRT3*rib)/(2*geometry.SQRT3)
        if corner>=maximum:
            messages.append('Pocket corner radius exceeds the space available inside a full cell; sharp corners may remain.')
    if hole>0 and rib>0 and corner>=0:
        diameter_limit=geometry.maximum_vertex_hole_diameter(rib,corner)
        tangency_limit=geometry.vertex_hole_tangency_diameter(rib,corner)
        if hole>tangency_limit+1e-7:
            messages.append(
                f'Vertex hole diameter exceeds the rounded-pocket contact limit '
                f'({tangency_limit*10:.3g} mm); circles may overlap triangular pockets.')
        elif abs(hole-tangency_limit)<=1e-7:
            messages.append('Vertex hole is tangent to the rounded pockets; '
                            'the minimum web thickness is zero and coincident sketch profiles may result.')
        elif hole>diameter_limit+1e-7:
            messages.append(
                'Vertex hole leaves less than the specified rib width of material '
                f'between hole and pocket (minimum web {rib*10:.3g} mm; '
                f'Auto Max Hole {diameter_limit*10:.3g} mm).')
    if hole<0:messages.append('Vertex-hole diameter must be non-negative.')
    if s['depth']<=0:messages.append('Extrusion depth must be positive for a cut.')
    for field,title in [('perimeter','Perimeter margin'),('holeclear','Void clearance'),
                        ('corner','Corner radius')]:
        if s[field]<0:messages.append(f'{title} must be non-negative.')
    if not 0<=s['minfraction']<=100:
        messages.append('Minimum retained cell area must be in the 0–100% range.')
    if not s.get('trim_boundary',True):
        messages.append('Boundary trimming is off: pockets and vertex circles may cross face edges and voids.')
    if outlines is not None:
        unrounded=sum(getattr(shape,'fillet_warnings',0) for shape in outlines)
        if unrounded:
            messages.append(f'{unrounded} tight corners could not accept the full radius; those corners remain sharp.')
        if hole>0 and not any(shape.circle for shape in outlines):
            messages.append('No vertex holes fit. Check diameter, clearance and grid position.')
    return messages


def _show_warnings(inputs, s, outlines=None):
    messages=_geometry_warnings(s,outlines)
    warning=inputs.itemById('warnings')
    if warning is not None:
        warning.text=('⚠ '+ '\n⚠ '.join(messages) if messages
                      else 'No geometric warnings.')
    return messages


def _show_manufacturing_report(inputs,report):
    if report is None:return
    messages=[]
    if report.rejected_corner_pockets:
        messages.append(f'{report.rejected_corner_pockets} clipped cut islands omitted: '
                        'the specified corner radius does not fit. '
                        'They are excluded from both preview and cut.')
    if report.unmachinable_corners:
        messages.append(f'{report.unmachinable_corners} pocket cells have unrounded corners; '
                        'inspect cutter feasibility.')
    if report.inaccessible_pockets:
        messages.append(f'{report.inaccessible_pockets} sampled pocket islands cannot '
                        'contain the specified cutter diameter.')
    if report.narrow_web_count:
        messages.append(f'{report.narrow_web_count} sampled material-web/clearance '
                        'violations against rib width and boundary settings (red outlines).')
    if messages:
        field=inputs.itemById('warnings')
        if field.text=='No geometric warnings.':field.text=''
        field.text+=(('\n' if field.text else '')+'⚠ '+'\n⚠ '.join(messages))


def _advisory_field_errors(s):
    """Return the exact inputs implicated by geometric invalidity/advisories."""
    issues = {}
    def flag(*keys):
        for key in keys:
            issues[key] = True
    pitch, rib, radius, hole = (s[k] for k in
                               ('pitch', 'rib', 'corner', 'nodehole'))
    if pitch <= 0: flag('pitch')
    if rib <= 0: flag('rib')
    if pitch > 0 and rib >= pitch/geometry.SQRT3: flag('pitch','rib')
    if pitch > geometry.SQRT3 * rib and radius > 0:
        maximum = (pitch-geometry.SQRT3*rib)/(2*geometry.SQRT3)
        if radius >= maximum: flag('corner')
    if hole < 0 or (rib > 0 and hole > geometry.maximum_vertex_hole_diameter(rib,radius)+1e-7): flag('nodehole')
    if s['perimeter'] < 0: flag('perimeter')
    if s['holeclear'] < 0: flag('holeclear')
    if radius < 0: flag('corner')
    if s.get('tool_diameter',0.)<0:flag('tool_diameter')
    if s.get('tool_diameter',0.)>0 and radius<s['tool_diameter']/2:
        flag('corner','tool_diameter')
    if not 0 <= s['minfraction'] <= 100: flag('minfraction')
    return issues


def _refresh_field_feedback(inputs, outlines=None):
    """Show advisory field tooltips and detailed warnings without blocking OK.

    Fusion may disable OK whenever a StringValueCommandInput has
    `isValueError=True`, even when validateInputs explicitly permits execution.
    Accordingly, clear native error flags for all advisory expression fields.
    Conversion/execution errors are reported on an attempted cut instead.
    """
    units = _units_manager()
    invalid_expressions = {}
    for key in ADVISORY_INPUT_UNITS:
        try:
            _input_number(inputs, key, units)
        except ValueError as error:
            invalid_expressions[key] = str(error)
    if invalid_expressions:
        s = None
        errors = dict(invalid_expressions)
    else:
        s = _inputs_to_settings(inputs)
        errors = _advisory_field_errors(s)
    fit_min = fit_max = None
    if 'fit_min_pitch' not in invalid_expressions:
        fit_min = _input_number(inputs, 'fit_min_pitch', units)
    if 'fit_max_pitch' not in invalid_expressions:
        fit_max = _input_number(inputs, 'fit_max_pitch', units)
    fit_range_bad = (fit_min is not None and fit_max is not None and
                     (fit_min <= 0 or fit_max <= fit_min))
    if fit_range_bad:
        errors.update(fit_min_pitch=True, fit_max_pitch=True)

    for key in ADVISORY_INPUT_UNITS:
        field = inputs.itemById(key)
        # This flag was the cause of the disabled OK button in Fusion.
        if field.isValueError:
            field.isValueError = False
        field.tooltip = ('⚠ Check Geometry warnings below for this value.'
                         if key in errors else '')
    if invalid_expressions:
        lines = list(invalid_expressions.values())
    else:
        lines = _geometry_warnings(s, outlines) if s else []
    if fit_range_bad:
        lines.append('Auto Fit pitch range requires 0 < minimum < maximum.')
    text = '⚠ ' + '\n⚠ '.join(lines) if lines else 'No geometric warnings.'
    warning_field = inputs.itemById('warnings')
    if warning_field.text != text:
        warning_field.text = text
    return s


def _placement(inputs,face,frame,s):
    """Reference point and edge selected in the existing component frame."""
    origin=None
    if s['origin_mode']=='Selected point':
        field=inputs.itemById('origin_point')
        if field.selectionCount!=1:
            raise ValueError('Select a sketch point or model vertex for the grid origin.')
        entity=field.selection(0).entity
        if entity.nativeObject:entity=entity.nativeObject
        if entity.objectType==adsk.fusion.SketchPoint.classType():
            point=entity.worldGeometry
            if entity.parentSketch.parentComponent!=face.body.parentComponent:
                raise ValueError('Origin point must belong to the target component.')
        else:
            point=entity.geometry
            if entity.body.parentComponent!=face.body.parentComponent:
                raise ValueError('Origin vertex must belong to the target component.')
        off=frame.origin.vectorTo(point)
        if abs(off.dotProduct(frame.n))>1e-4:
            raise ValueError('Origin point must lie in the target face plane.')
        origin=frame.to_xy(point)
    rotation=math.degrees(s['angle'])
    if s['alignment']=='Selected edge':
        field=inputs.itemById('align_edge')
        if field.selectionCount!=1:
            raise ValueError('Select a straight model edge or sketch line for alignment.')
        edge=field.selection(0).entity
        if edge.nativeObject:edge=edge.nativeObject
        if edge.objectType==adsk.fusion.SketchLine.classType():
            if edge.parentSketch.parentComponent!=face.body.parentComponent:
                raise ValueError('Alignment line must belong to the target component.')
            curve=edge.worldGeometry
            p,q=curve.startPoint,curve.endPoint
        else:
            if edge.body.parentComponent!=face.body.parentComponent:
                raise ValueError('Alignment edge must belong to the target component.')
            p,q=edge.startVertex.geometry,edge.endVertex.geometry
        uvp,uvq=frame.to_xy(p),frame.to_xy(q)
        v=geometry.sub(uvq,uvp)
        if geometry.norm(v)<1e-7:
            raise ValueError('Selected alignment edge has no in-plane direction.')
        # A line has no inherent forward direction. Normalise to ±90 degrees
        # so its arbitrary B-Rep edge orientation cannot flip the pattern.
        direction=math.degrees(math.atan2(v[1],v[0]))
        direction=(direction+90)%180-90
        rotation+=direction
    return origin,rotation


def _source_geometry(inputs, cache=None):
    started=time.perf_counter()
    face,profile=_selected(inputs)
    s=_inputs_to_settings(inputs)
    _validate_settings(s)
    # Sample curved boundaries to <= 0.025 mm or 1/8 of rib width.
    tolerance=max(0.0005,min(0.0025,s['rib']/8))
    source_key=(face.entityToken,profile.entityToken if profile else None,tolerance)
    if cache is not None and cache.get('key')==source_key:
        frame,regions=cache['frame'],cache['regions']
        preview_timing.log('fusion.source_cache_hit', elapsed=time.perf_counter()-started)
    else:
        frame=FaceFrame(face)
        face_region=_face_region(face,frame,tolerance)
        preview_timing.log('fusion.face_extracted', elapsed=time.perf_counter()-started, loops=len(face_region.loops))
        regions=[face_region]
        if profile:
            # Disallow a non-coplanar mask before any sketch geometry is projected.
            sketch=profile.parentSketch
            p0=sketch.origin
            offset=frame.origin.vectorTo(p0)
            if abs(offset.dotProduct(frame.n))>1e-4 or abs(sketch.xDirection.crossProduct(sketch.yDirection).dotProduct(frame.n))<0.9999:
                raise ValueError('Bounding sketch profile must be coplanar with the selected face.')
            regions.append(_profile_region(profile,frame,tolerance))
        if cache is not None:
            cache.clear()
            cache.update(key=source_key,frame=frame,regions=regions)
    origin,rotation=_placement(inputs,face,frame,s)
    preview_timing.log('fusion.source_ready', elapsed=time.perf_counter()-started)
    return face,profile,frame,s,regions,origin,rotation


def _compute(inputs,max_cells=1600,source_cache=None):
    face,profile,frame,s,regions,origin,rotation=_source_geometry(inputs,source_cache)
    _validate_settings(s)
    arguments=(regions,s['pitch'],s['rib'],s['perimeter'],s['holeclear'],
               s['dx'],s['dy'],rotation,s['corner'])
    options=dict(min_area_fraction=s['minfraction']/100,max_cells=max_cells,
                 vertex_hole_diameter=s['nodehole'],base_origin=origin,
                 anchor='triangle' if s['anchor']=='Triangle centre' else 'vertex')
    if s['trim_boundary'] and s['corner']>0 and s['backend']!='geos':
        outlines,_=tool_center.make_toolcentre_pockets(*arguments,**options)
    else:
        outlines=geometry.make_pockets(*arguments,backend=s['backend'],
            trim_boundary=s['trim_boundary'],**options)
    outlines,_=manufacturability.screen(outlines,regions,s)
    if not outlines:raise ValueError('No pockets fit this region. Reduce margins or cell pitch.')
    return face,profile,frame,s,regions,outlines


def _draw_preview(session,data):
    started=time.perf_counter()
    preview_timing.log('fusion.draw_begin', shapes=len(data[-1]))
    session.clear_preview()
    face,profile,frame,settings,regions,outlines=data
    component=face.body.parentComponent
    graphics=component.customGraphicsGroups.add()
    session.graphics=graphics
    # Fusion can invoke executePreview repeatedly with unchanged geometry,
    # particularly while an Auto Fit progress label is being updated. The
    # previous implementation retransformed ~12,000 vertices on *every*
    # redraw. Retain the coordinate array for this exact immutable result;
    # Fusion may roll back its graphics group without invalidating the data.
    if getattr(session,'_preview_coords_source',None) is outlines:
        coords=session._preview_coords
    else:
        coords=[]
        for shape in outlines:
            for poly in shape.loops:
                for a,b in zip(poly,poly[1:]+poly[:1]):
                    for uv in (a,b):
                        pt=frame.to_world(uv,lift=0.006)
                        coords.extend((pt.x,pt.y,pt.z))
        session._preview_coords_source=outlines
        session._preview_coords=coords
    preview_timing.log('fusion.draw_coordinates', elapsed=time.perf_counter()-started, vertices=len(coords)//3)
    if not coords:return
    obj=graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(coords),[],False)
    obj.weight=2
    obj.color=adsk.fusion.CustomGraphicsSolidColorEffect.create(
        adsk.core.Color.create(12,171,235,255))
    # Non-destructive highlighting of sampled clearance and cutter advisories.
    report=getattr(session,'manufacturing_report',None)
    violations=set(getattr(report,'web_shapes',()))
    violations.update(getattr(report,'cutter_shapes',()))
    if violations:
        flagged=[]
        for i in violations:
            if not 0<=i<len(outlines):continue
            for poly in outlines[i].loops:
                for a,b in zip(poly,poly[1:]+poly[:1]):
                    for uv in (a,b):
                        pt=frame.to_world(uv,lift=0.008)
                        flagged.extend((pt.x,pt.y,pt.z))
        if flagged:
            warning=graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(flagged),[],False)
            warning.weight=3
            warning.color=adsk.fusion.CustomGraphicsSolidColorEffect.create(
                adsk.core.Color.create(240,75,47,255))
    APP.activeViewport.refresh()
    preview_timing.log('fusion.draw_complete', elapsed=time.perf_counter()-started)


def _write_sketch_segment(sketch,frame,segment):
    """Convert one directed planar curve to native Fusion sketch geometry.

    Input geometry is deliberately detached from Fusion for background work;
    only this main-thread function creates Fusion API curve objects. Native
    conics/NURBS are preserved. General offsets become bounded-error cubic
    splines because their exact offsets are usually not rational B-splines.
    """
    curves=sketch.sketchCurves
    def sketch_point(point):
        return sketch.modelToSketchSpace(frame.to_world(point))

    if isinstance(segment,geometry.Arc2D):
        if abs(segment.sweep)>=math.tau-1e-7:
            created=curves.sketchCircles.addByCenterRadius(
                sketch_point(segment.center),segment.radius)
        else:
            created=curves.sketchArcs.addByThreePoints(
                sketch_point(segment.start),sketch_point(segment.middle),
                sketch_point(segment.end))
        if not created:
            raise RuntimeError('Unable to create a native circular sketch curve.')
        return [created]

    if isinstance(segment,exact_curves.Ellipse):
        if abs(segment.sweep)>=math.tau-1e-7:
            created=curves.sketchEllipses.add(
                sketch_point(segment.center),
                sketch_point(exact_curves.add(segment.center,segment.major)),
                sketch_point(exact_curves.add(segment.center,segment.minor)))
            if not created:
                raise RuntimeError('Unable to create a native ellipse.')
            return [created]
        else:
            created_segments=[]
            for points,weights in exact_curves.ellipse_quadratics(segment):
                nurbs=adsk.core.NurbsCurve3D.createRational(
                    [sketch_point(pt) for pt in points],2,
                    [0.,0.,0.,1.,1.,1.],list(weights),False)
                created=curves.sketchFixedSplines.addByNurbsCurve(nurbs) if nurbs else None
                if not created:
                    raise RuntimeError('Unable to create a rational conic spline.')
                created_segments.append(created)
        return created_segments

    if isinstance(segment,exact_curves.Nurbs):
        exact=exact_curves.trimmed_nurbs(segment)
        nurbs=adsk.core.NurbsCurve3D.createRational(
            [sketch_point(pt) for pt in exact.controls],exact.degree,
            list(exact.knots),list(exact.weights),False)
        created=curves.sketchFixedSplines.addByNurbsCurve(nurbs) if nurbs else None
        if not created:
            raise RuntimeError('Unable to create a native NURBS sketch curve.')
        return [created]

    if isinstance(segment,(exact_curves.Offset,OffsetInterval)):
        # Preserve primitives when an offset remains an exact line or circle.
        # Cleaned offset intervals must use the original parameterisation;
        # sectioning the base before offsetting can move its spline endpoints.
        underlying=(segment.source if isinstance(segment,OffsetInterval)
                    else segment)
        if isinstance(underlying.base,exact_curves.Line):
            return _write_sketch_segment(sketch,frame,
                exact_curves.Line(segment.start,segment.end))
        if isinstance(underlying.base,exact_curves.Arc):
            arc=underlying.base
            sweep=(arc.sweep*(segment.u1-segment.u0)
                   if isinstance(segment,OffsetInterval) else arc.sweep)
            radius=exact_curves.length(exact_curves.sub(segment.start,arc.center))
            if radius>1e-9:
                return _write_sketch_segment(sketch,frame,
                    exact_curves.Arc(arc.center,segment.start,segment.end,sweep))
        # Generic spline/ellipse offsets remain one bounded-error multi-span
        # NURBS per retained section. This also handles cleaned parametric
        # intervals from self-intersecting source offsets.
        points,knots=exact_curves.approximate_cubic_nurbs(segment,1e-4)
        nurbs=adsk.core.NurbsCurve3D.createNonRational(
            [sketch_point(pt) for pt in points],3,list(knots),False)
        created=curves.sketchFixedSplines.addByNurbsCurve(nurbs) if nurbs else None
        if not created:
            raise RuntimeError('Unable to create a smooth offset spline.')
        return [created]

    if isinstance(segment,exact_curves.Line):
        created=curves.sketchLines.addByTwoPoints(
                sketch_point(segment.start),sketch_point(segment.end))
        if not created:
            raise RuntimeError('Unable to create a native sketch line.')
        return [created]
    raise TypeError('Unsupported output curve: '+type(segment).__name__)


def _match_generated_profiles(sketch, required, frame=None, sources=None,
                              report=None):
    """Select cut profiles by their actual Fusion sketch-curve ownership.

    Using an arbitrary Profile.face.pointOnFace coordinate and retesting it
    against our sampled contours can reject an otherwise valid pocket near a
    curved boundary. The outer ProfileLoop identifies the real Fusion profile
    and ProfileCurve.sketchEntity identifies the geometry that generated it.

    Each emitted SketchCurve carries a persistent source-loop attribute.  Do
    not compare Autodesk entityToken strings: the API explicitly documents
    that the token for the same entity may change even while it remains valid.
    Only generated *positive* loops appear in required; a protected hole's
    outer profile loop therefore cannot select the void interior by mistake.
    """
    selected=[]
    matched=set()
    unknown=0
    fallback_matches=0
    for index in range(sketch.profiles.count):
        item=sketch.profiles.item(index)
        outer_loops=[item.profileLoops.item(j)
                     for j in range(item.profileLoops.count)
                     if item.profileLoops.item(j).isOuter]
        if len(outer_loops)!=1:
            unknown+=1
            continue
        outer=outer_loops[0]
        owners=[]
        for j in range(outer.profileCurves.count):
            entity=outer.profileCurves.item(j).sketchEntity
            try:
                attr=(entity.attributes.itemByName(ATTRIBUTE_GROUP,'sourceLoop')
                      if entity else None)
            except (AttributeError,RuntimeError):
                attr=None
            owners.append(attr.value if attr else None)
        owner=(owners[0] if owners and owners[0] in required and
               all(o==owners[0] for o in owners) else None)
        if owner is None and frame is not None and sources:
            # Fusion may split/rebuild a SketchCurve when computing sketch
            # profiles; the ProfileCurve.sketchEntity association can then be
            # absent or differ from the originally tagged sketch entity.
            # Check the actual native output curves at Fusion's interior
            # profile point. Bounding boxes only cull candidate checks; they
            # are NOT the sampled-polygon containment test used before v0.8.3.
            try:
                point=frame.to_xy(sketch.sketchToModelSpace(item.face.pointOnFace))
                candidates=[]
                for key,(bbox,curve_loop,holes,circle) in sources.items():
                    if (bbox[0]-1e-6 <= point[0] <= bbox[2]+1e-6 and
                        bbox[1]-1e-6 <= point[1] <= bbox[3]+1e-6):
                        inside=(math.hypot(point[0]-circle[0][0],
                                           point[1]-circle[0][1]) < circle[1]
                                if circle else exact_curves.loop_contains(curve_loop,point))
                        if inside and not any(exact_curves.loop_contains(h,point)
                                              for h in holes):
                            candidates.append(key)
                if len(candidates)==1:
                    owner=candidates[0]
                    fallback_matches+=1
            except (AttributeError,RuntimeError,ValueError,ZeroDivisionError):
                pass
        if owner is None:
            unknown+=1
            continue
        if owner not in required:
            continue  # A protected inner hole, not a pocket to cut.
        selected.append(item)
        matched.add(owner)
    missing=required-matched
    if report is not None:
        report.update(expected=len(required),matched=len(matched),
                      missing=sorted(missing),unknown=unknown,
                      fallback=fallback_matches,
                      fusion_profiles=sketch.profiles.count)
    return selected


def _create_feature(data):
    face,profile,frame,settings,regions,outlines=data
    component=face.body.parentComponent
    sketches=component.sketches
    # Capture persistent references before a CUT can split or invalidate the face.
    source_face_token=face.entityToken
    source_profile_token=profile.entityToken if profile else None
    sketch=None
    try:
        # Important: addWithoutEdges avoids including the original face outline
        # as sketch geometry, which would generate unrelated profiles.
        sketch=sketches.addWithoutEdges(face)
        sketch.name='Isogrid · pocket outlines'
        circles=sketch.sketchCurves.sketchCircles
        sketch.isComputeDeferred=True
        required=set()
        source_loops={}
        for shape_index,shape in enumerate(outlines):
            # Untrimmed output intentionally includes complete triangles beyond
            # the face. Keep their editable sketch curves, but do not include
            # wholly exterior profiles in the extrusion cut.
            should_cut=True
            if not settings['trim_boundary']:
                fragments=geometry.clip_pocket(shape.outline,regions)
                should_cut=(sum(geometry.area(poly) for poly in fragments)>1e-8)
            if shape.circle:
                center,radius=shape.circle
                center_pt=sketch.modelToSketchSpace(frame.to_world(center))
                entity=circles.addByCenterRadius(center_pt,radius)
                if not entity:raise RuntimeError('Unable to create native vertex-hole circle.')
                owner=f'{shape_index}:0'
                try:entity.attributes.add(ATTRIBUTE_GROUP,'sourceLoop',owner)
                except (AttributeError,RuntimeError):pass
                if should_cut:
                    required.add(owner)
                    source_loops[owner]=(geometry.bounds(shape.loops[0]),
                                         None,[],shape.circle)
                continue
            loops=shape.curve_loops or [geometry.polyline_curves(p) for p in shape.loops]
            holes=[loop for loop,poly in zip(loops,shape.loops)
                   if geometry.area(poly)<0]
            for loop_index,curved_loop in enumerate(loops):
                owner=f'{shape_index}:{loop_index}'
                if should_cut and geometry.area(shape.loops[loop_index])>0:
                    required.add(owner)
                    source_loops[owner]=(geometry.bounds(shape.loops[loop_index]),
                                         curved_loop,holes,None)
                for segment in curved_loop:
                    for entity in _write_sketch_segment(sketch,frame,segment):
                        try:entity.attributes.add(ATTRIBUTE_GROUP,'sourceLoop',owner)
                        except (AttributeError,RuntimeError):pass
        sketch.isComputeDeferred=False
        # Match Fusion's *actual* closed profiles by the SketchCurve entities
        # that define their outer boundary, rather than approximated point
        # containment (which could silently drop a valid pocket near an edge).
        match_report={}
        profiles=_match_generated_profiles(sketch,required,frame,source_loops,
                                           match_report)
        chosen=adsk.core.ObjectCollection.create()
        for item in profiles:chosen.add(item)
        APP.log('Isogrid cut profile matching: '+str(match_report))
        if chosen.count==0:
            raise RuntimeError('Fusion produced no usable pocket profiles; '
                               'see the profile matching report in Fusion logs.')
        extrudes=component.features.extrudeFeatures
        feature_input=extrudes.createInput(chosen,adsk.fusion.FeatureOperations.CutFeatureOperation)
        distance=adsk.core.ValueInput.createByString(settings['depth_expression'])
        extent=adsk.fusion.DistanceExtentDefinition.create(distance)
        sketch_normal=sketch.xDirection.crossProduct(sketch.yDirection)
        direction=(adsk.fusion.ExtentDirections.NegativeExtentDirection
                   if sketch_normal.dotProduct(frame.n)>0 else
                   adsk.fusion.ExtentDirections.PositiveExtentDirection)
        feature_input.setOneSideExtent(extent,direction)
        feature_input.participantBodies=[face.body]
        feature=extrudes.add(feature_input)
        if not feature:raise RuntimeError('Extrusion cut returned no feature.')
        feature.name='Isogrid · pocket cut'
        sketch.isVisible=False
        if match_report['missing']:
            try:
                feature.attributes.add(ATTRIBUTE_GROUP,'missingContours',
                    json.dumps(match_report))
            except Exception:
                APP.log('Isogrid could not attach the incomplete-profile report.')
            APP.log('Isogrid incomplete cut: missing generated contour IDs '+
                    ', '.join(match_report['missing'][:20]))
            # A partial cut is preferable to silently producing nothing, but
            # the shortfall must be explicit to the user.
            try:
                UI.messageBox(f'Isogrid cut created with {match_report["matched"]} '
                    f'of {match_report["expected"]} generated contours. '
                    f'{len(match_report["missing"])} failed to form a selectable '
                    'Fusion sketch profile. The missing IDs are in the Fusion log.')
            except Exception:
                APP.log('Isogrid could not display the incomplete-cut warning.')
        # Keep a record of the choices for inspection/re-use in future builds.
        saved=dict(settings)
        saved['faceToken']=source_face_token
        saved['sketchProfileToken']=source_profile_token
        saved['schemaVersion']=8
        feature.attributes.add(ATTRIBUTE_GROUP,'settings',json.dumps(saved))
        sketch.attributes.add(ATTRIBUTE_GROUP,'settings',json.dumps(saved))
        return feature
    except:
        if sketch:
            try:
                sketch.isComputeDeferred=False
                sketch.deleteMe()
            except:pass
        raise


class Session:
    """Main-thread Fusion state; geometry work is delegated to LatestWorker."""
    def __init__(self):
        self.command = None
        self._shown_update = None
        self.graphics = None
        self.cache = None
        self.cache_signature = None
        self.source_cache = {}
        self.fits = []
        self.fit_summary = ''
        self.updating = False
        self.fit_alignment_offset = 0.0
        self.inputs = None
        self.alive = True
        self.busy = False
        self.fit_running = False
        self.pending_kind = None
        self.revision = None
        self.last_signature = None
        self.failed_signature = None
        self.snapshot = None
        self.manufacturing_report = None
        self.presets = presets.Store()
        self.preset_manual_membership = set()
        self.worker = async_engine.LatestWorker(
            lambda: APP.fireCustomEvent(CUSTOM_EVENT_ID))

    def dispose(self):
        preview_timing.log('fusion.session_dispose', busy=self.busy, revision=self.revision)
        self.alive = False
        self.worker.close()
        self.clear_preview()
        self.command = None
        self.cache = None
        self.snapshot = None
        self.source_cache.clear()

    def clear_preview(self):
        if self.graphics:
            try: self.graphics.deleteMe()
            except: pass
            self.graphics = None

    def _activity(self, state, detail=''):
        if not self.alive or self.inputs is None:
            return
        colour = {'working':'#d48b00', 'ready':'#198a41',
                  'error':'#c0392b','idle':'#888888'}[state]
        name = {'working':'Working', 'ready':'Ready',
                'error':'Error','idle':'Idle'}[state]
        try:
            self.inputs.itemById('activity').formattedText = (
                f'<span style="color:{colour};"><b>● {name}</b></span>'
                + (' — ' + html.escape(detail) if detail else ''))
        except: pass

    def _source(self, inputs):
        return _source_geometry(inputs, self.source_cache)

    def _snapshot(self, inputs):
        face,profile,frame,s,regions,origin,rotation = self._source(inputs)
        anchor='triangle' if s['anchor']=='Triangle centre' else 'vertex'
        source_key=self.source_cache['key']
        # All these objects are pure Python except face/profile/frame, which
        # are intentionally retained on the UI thread, outside the payload.
        # Extrusion depth is a downstream CAD parameter, not 2D geometry.
        geom_s=((k,v) for k,v in s.items()
                if k not in ('depth','depth_expression'))
        signature=(source_key,tuple(sorted(geom_s)),origin,rotation)
        prep_key=(source_key,s['perimeter'],s['holeclear'],s['backend'])
        payload={'regions':regions, 'settings':s.copy(), 'origin':origin,
                 'rotation':rotation, 'anchor':anchor,'prep_key':prep_key}
        return signature,(face,profile,frame,s,regions),payload

    def _saved_text(self,inputs):
        field=inputs.itemById('saved_result')
        if field is None:return
        if self.cache is None:
            field.text='Waiting for exact geometry…'
            return
        try:
            volume=saved_mass.saved_volume_cm3(
                self.cache[-1],_input_number(inputs,'depth'))
            mass=volume*_selected_density(inputs)
            amount=(f'{mass/1000:.3f} kg' if mass>=1000 else f'{mass:.1f} g')
            field.text=f'Removed ~{volume:.2f} cm³  ·  Saved ~{amount}'
        except (ValueError,KeyError) as exc:
            field.text='Savings: '+str(exc)

    def request_preview(self, inputs, force=False):
        started=time.perf_counter()
        if not self.alive or self.updating:
            return
        try:
            _refresh_field_feedback(inputs)
            if inputs.itemById('face').selectionCount<1:
                self.worker.cancel()
                self.busy=False;self.fit_running=False
                self.last_signature=None;self.cache=None;self.cache_signature=None
                self.clear_preview()
                self._activity('idle','Select a face')
                inputs.itemById('status').text='Select a planar face to preview.'
                return
            preview_timing.log('fusion.snapshot_begin')
            signature,model,payload=self._snapshot(inputs)
            preview_timing.log('fusion.snapshot_complete', elapsed=time.perf_counter()-started)
            if not force and signature==self.failed_signature:
                return  # Do not automatically retry an identical failed preview.
            if not force and signature==self.last_signature:
                if self.cache_signature==signature:
                    # A depth-only edit reuses the existing pocket geometry.
                    self.cache[3].update(depth=payload['settings']['depth'],
                        depth_expression=payload['settings']['depth_expression'])
                    if not inputs.itemById('show_preview').value:
                        self.clear_preview()
                    _show_manufacturing_report(inputs,self.manufacturing_report)
                    self._saved_text(inputs)
                return
            self.failed_signature=None
            self.last_signature=signature
            self.cache=None
            self.cache_signature=None
            self.manufacturing_report=None
            self.clear_preview()   # Prevent stale outlines being mistaken for current geometry.
            self.snapshot=(signature,model,payload)
            self.busy=True
            self.fit_running=False
            self.pending_kind='preview'
            self.revision=self.worker.submit('preview',payload)
            preview_timing.log('fusion.preview_submitted', revision=self.revision, elapsed=time.perf_counter()-started)
            self._activity('working','Computing preview')
            inputs.itemById('status').text='Computing 2D pockets…'
            self._saved_text(inputs)
        except Exception as error:
            preview_timing.log('fusion.preview_error', elapsed=time.perf_counter()-started, error=str(error))
            self.worker.cancel()
            self.busy=False;self.fit_running=False
            self.pending_kind=None
            self.last_signature=None
            self.cache=None;self.cache_signature=None
            self.clear_preview()
            self._activity('error',str(error))
            inputs.itemById('status').text='Preview: '+str(error)

    def preview(self,args):
        preview_timing.log('fusion.execute_preview_begin')
        # Fusion rolls back the previous executePreview transaction before
        # calling this handler. Custom graphics must therefore be constructed
        # HERE, after rollback, rather than in the asynchronous result event.
        # The worker still performs all polygon computation off the UI thread.
        if self.updating:
            return
        inputs=args.command.commandInputs
        if not self.fit_running:
            self.request_preview(inputs)
        if (self.cache is not None and
            self.cache_signature==self.last_signature and
            inputs.itemById('show_preview').value):
            try:
                _draw_preview(self,self.cache)
            except Exception as exc:
                self._activity('error','Preview rendering: '+str(exc))
                APP.log('Isogrid graphics failure:\n'+traceback.format_exc())
        else:
            self.clear_preview()

    def redraw_ready_preview(self):
        """Request a new command preview transaction on Fusion's UI thread.

        A custom event is suitable for transferring results, but changes to
        Fusion custom-graphics groups must be made within executePreview.
        """
        if not self.alive or self.command is None:
            return
        preview_timing.log('fusion.request_redraw_begin')
        if not self.command.doExecutePreview():
            APP.log('Isogrid could not request a new executePreview transaction.')

    def _preview_text(self,inputs,data):
        _,_,_,_,_,outlines=data
        total=sum(len(shape.loops) for shape in outlines)
        holes=sum(shape.circle is not None for shape in outlines)
        _refresh_field_feedback(inputs,outlines)
        _show_manufacturing_report(inputs,self.manufacturing_report)
        self._saved_text(inputs)
        inputs.itemById('status').text=(f'{self.fit_summary}'
             f'{len(outlines)-holes} cells · {holes} vertex holes · {total} contours. '
             f'Geometry: {geometry.geometry_backend(_inputs_to_settings(inputs)["backend"])}. '
             'Cyan outlines show the cut areas. Press OK to generate the solid cut.')

    def invalidate_fits(self,inputs):
        self.fits=[]
        self.fit_summary=''
        choices=inputs.itemById('fit_choice')
        choices.listItems.clear()
        choices.listItems.add('Click Find Fits to calculate layouts',True)

    def apply_fit(self,inputs,index):
        if not 0<=index<len(self.fits):return
        fit=self.fits[index]
        self.updating=True
        try:
            for name,value in (('pitch',fit.pitch),('dx',fit.dx),('dy',fit.dy)):
                _set_input_number(inputs,name,value)
            rotation_control=inputs.itemById('angle')
            rotation_control.value=math.radians(fit.rotation-self.fit_alignment_offset)
            self.fit_summary=(f'Fit: {fit.label} · ~{fit.area*100:.1f} mm² estimated removal · '
                f'{fit.partials} partial pockets · longest connected run '
                f'{fit.longest_partial_run} · fit score {fit.fit_quality:.3f}. ')
        finally:
            self.updating=False
        # Programmatic input changes are not guaranteed to fire executePreview.
        _refresh_field_feedback(inputs)
        self.request_preview(inputs)

    def run_fit(self,inputs):
        if self.updating:return
        signature,model,payload=self._snapshot(inputs)
        low=_input_number(inputs,'fit_min_pitch')
        high=_input_number(inputs,'fit_max_pitch')
        if low<=0 or high<=low:
            raise ValueError('Auto Fit pitch range must satisfy 0 < minimum < maximum.')
        effort=inputs.itemById('fit_effort').selectedItem.name
        evaluations={'Quick (120 tests)':120,
                     'Standard (320 tests)':320,
                     'Thorough (1000 tests)':1000}[effort]
        do_rotation=inputs.itemById('fit_rotation').value
        self.invalidate_fits(inputs)
        payload.update(low=low,high=high,evaluations=evaluations,
                       allow_rotation=do_rotation)
        self.fit_alignment_offset=payload['rotation']-math.degrees(payload['settings']['angle'])
        self.fit_running=True
        self.busy=True
        self.pending_kind='fit'
        self.revision=self.worker.submit('fit',payload)
        self._activity('working',f'Auto Fit 0/{evaluations}')
        inputs.itemById('status').text='Searching for layouts in the background… '

    def consume(self):
        """Invoked from Fusion's registered custom event on the main thread."""
        if not self.alive:return
        for message in self.worker.drain():
            if message['revision']!=self.revision:
                continue
            kind=message['kind']
            preview_timing.log('fusion.worker_message', kind=kind, revision=message['revision'])
            if kind=='progress':
                if self.fit_running:
                    self._activity('working',f'Auto Fit {message["done"]}/{message["total"]}')
                continue
            if kind=='error':
                if message['source']=='preview' and self.snapshot is not None:
                    self.failed_signature=self.snapshot[0]
                preview_timing.log('fusion.preview_failed', error=message['message'])
                self.busy=False;self.fit_running=False
                self.pending_kind=None
                self.last_signature=None
                self.cache=None;self.cache_signature=None
                self.clear_preview()
                self._activity('error',message['message'])
                self.inputs.itemById('status').text=(
                    ('Auto Fit' if message['source']=='fit' else 'Preview')
                    + ': ' + message['message'])
                APP.log('Isogrid background '+message['source']+' failure:\n'+message['traceback'])
                continue
            if kind=='preview':
                if self.pending_kind!='preview' or not self.snapshot:
                    continue
                signature,model,_=self.snapshot
                face,profile,frame,s,regions=model
                current_settings=_inputs_to_settings(self.inputs)
                s.update(depth=current_settings['depth'],
                         depth_expression=current_settings['depth_expression'])
                data=(face,profile,frame,s,regions,message['value'])
                self.cache=data;self.cache_signature=signature
                self.manufacturing_report=message.get('manufacturing_report')
                self.busy=False;self.pending_kind=None
                self._preview_text(self.inputs,data)
                self._activity('ready','Preview current')
                # This event only delivers geometry. Creating graphics here
                # leaves them vulnerable to the next preview rollback.
                try:
                    self.redraw_ready_preview()
                except Exception as exc:
                    self._activity('error','Preview rendering: '+str(exc))
                    APP.log('Isogrid graphics failure:\n'+traceback.format_exc())
            elif kind=='fit':
                if self.pending_kind!='fit':continue
                self.fit_running=False
                self.busy=False
                self.pending_kind=None
                self.fits=message['value']
                choices=self.inputs.itemById('fit_choice')
                self.updating=True
                try:
                    choices.listItems.clear()
                    for i,candidate in enumerate(self.fits):
                        title=(f'{i+1}. {candidate.label} · {candidate.pitch*10:.2f} mm · '
                               f'{candidate.partials} partial · fit {candidate.fit_quality:.2f}')
                        choices.listItems.add(title,i==0)
                finally:
                    self.updating=False
                if self.fits:self.apply_fit(self.inputs,0)
                else:self._activity('idle','No fitting layouts')

def _update_placement_visibility(inputs):
    origin=inputs.itemById('origin_mode').selectedItem.name
    alignment=inputs.itemById('alignment').selectedItem.name
    inputs.itemById('origin_point').isVisible=origin=='Selected point'
    inputs.itemById('align_edge').isVisible=alignment=='Selected edge'


class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self,args):
        try:
            command=args.command
            command.setDialogInitialSize(445,760)
            command.isExecutedWhenPreEmpted=False
            inputs=command.commandInputs
            face=inputs.addSelectionInput('face','Target face','Select the planar face to texture')
            face.addSelectionFilter('PlanarFaces');face.setSelectionLimits(1,1)
            mask=inputs.addSelectionInput('mask','Optional sketch boundary',
                    'Select an existing closed sketch profile on that face (optional)')
            mask.addSelectionFilter('Profiles');mask.setSelectionLimits(0,1)
            def dropdown(id,title,names):
                d=inputs.addDropDownCommandInput(
                    id,title,adsk.core.DropDownStyles.TextListDropDownStyle)
                for i,name in enumerate(names):d.listItems.add(name,i==0)
                return d
            dropdown('origin_mode','Grid origin',('Face bounding centre','Selected point'))
            origin_point=inputs.addSelectionInput('origin_point','Origin point',
                            'Select a planar sketch point or model vertex')
            origin_point.addSelectionFilter('SketchPoints')
            origin_point.addSelectionFilter('Vertices')
            origin_point.setSelectionLimits(0,1)
            dropdown('anchor','Align origin to',('Grid vertex','Triangle centre'))
            dropdown('alignment','Grid alignment',('Face local axes','Selected edge'))
            # GEOS backend selection is disabled; pure Python is always used.
            # dropdown('backend_choice','Geometry backend',
            #          ('Automatic','Pure Python','GEOS accelerated'))
            align_edge=inputs.addSelectionInput('align_edge','Alignment edge',
                        'Select a straight model edge or sketch line to align the grid X axis')
            align_edge.addSelectionFilter('LinearEdges')
            align_edge.addSelectionFilter('SketchLines')
            align_edge.setSelectionLimits(0,1)
            defaults={
                'pitch':('Cell pitch','20 mm','mm'),
                'rib':('Rib width','2 mm','mm'),
                'depth':('Extrusion depth','2 mm','mm'),
                'perimeter':('Perimeter margin','3 mm','mm'),
                'holeclear':('Clearance at voids','3 mm','mm'),
                'dx':('X start offset','0 mm','mm'),
                'dy':('Y start offset','0 mm','mm'),
                'angle':('Grid rotation','0 deg','deg'),
                'corner':('Pocket corner radius','1.5 mm','mm'),
                'nodehole':('Vertex hole diameter (0 = off)','3 mm','mm'),
                'minfraction':('Minimum retained cell area (%)','5',''),
                'tool_diameter':('Cutter diameter (0 = off)','0 mm','mm'),
            }
            for key,(title,value,units) in defaults.items():
                if key in ADVISORY_INPUT_UNITS:
                    inputs.addStringValueInput(key,title,value)
                else:
                    vi=(adsk.core.ValueInput.createByString(value) if units
                        else adsk.core.ValueInput.createByReal(5))
                    inputs.addValueInput(key,title,units,vi)
                if key == 'nodehole':
                    auto_hole = inputs.addBoolValueInput(
                        'auto_nodehole', 'Auto Max Hole', False, '', False)
                    auto_hole.tooltip = (
                        'Set the largest nominal hole that preserves a minimum web equal '
                        'to rib width between the circular hole and adjacent rounded pockets. '
                        'For feasible 60° full-cell fillets this is 2 × corner radius.')
            inputs.addBoolValueInput('trim_boundary','Trim to boundary / voids',True,'',True)
            inputs.addStringValueInput('fit_min_pitch','Auto Fit minimum pitch','16 mm')
            inputs.addStringValueInput('fit_max_pitch','Auto Fit maximum pitch','28 mm')
            dropdown('fit_effort','Auto Fit search effort',(
                'Standard (320 tests)','Quick (120 tests)','Thorough (1000 tests)'))
            # Standard is the default; the drop-down permits faster or
            # more thorough searches when necessary.
            inputs.addBoolValueInput('fit_rotation','Include rotation in Auto Fit',True,'',False)
            inputs.addBoolValueInput('find_fits','Find Fits (optional)',False,'',False)
            dropdown('fit_choice','Auto Fit candidates',('Click Find Fits to calculate layouts',))
            inputs.itemById('fit_choice').tooltip=(
                'Select a computed fit to copy its pitch and X/Y offsets into the normal fields.')
            # Sparse, named user presets; membership is explicitly selectable.
            preset_group=inputs.addGroupCommandInput('preset_group','Parameter presets')
            preset_group.isExpanded=False
            controls=preset_group.children
            presets_dropdown=controls.addDropDownCommandInput(
                'preset_choice','Saved preset',adsk.core.DropDownStyles.TextListDropDownStyle)
            controls.addStringValueInput('preset_name','Name to save','')
            controls.addBoolValueInput('preset_save','Save selected values',False,'',False)
            controls.addBoolValueInput('preset_delete','Delete selected preset',False,'',False)
            fields_group=controls.addGroupCommandInput('preset_fields_group','Values to include when saving')
            # Fusion prohibits collapsing a nested group without an enable checkbox.
            # Only the outer Parameter presets group is collapsible.
            fields_group.isExpanded=True
            for key in presets.FIELDS:
                fields_group.children.addBoolValueInput('preset_include_'+key,
                    presets.LABELS[key],True,'',False)
            controls.addTextBoxCommandInput('preset_status','Preset status',
                'Tick only the values this preset should change.',2,True)
            inputs.addBoolValueInput('show_preview','Show outline preview',True,'',True)
            dropdown('material_density','Material density',
                     ('Aluminium','Steel','UHMW','1','User'))
            custom=inputs.addStringValueInput('custom_density',
                'Custom density (g/cm³)','1.0')
            custom.isVisible=False
            inputs.addTextBoxCommandInput('saved_result','Volume / mass saved',
                'Waiting for exact geometry…',1,True)
            inputs.addTextBoxCommandInput('activity','Geometry worker',
                '<span style="color:#888888;"><b>● Idle</b></span> — Select a face',1,True)
            inputs.addTextBoxCommandInput('status','Pattern','Select a planar face to preview.',3,True)
            inputs.addTextBoxCommandInput('warnings','Geometry warnings',
                'No geometric warnings.',5,True)
            notice=inputs.addTextBoxCommandInput('update_notice','Update','',2,True)
            notice.isVisible=False
            inputs.addBoolValueInput('check_update','Check for Updates',False,'',False)
            button=inputs.addBoolValueInput('install_update','Install Update',False,'',False)
            button.isVisible=False
            _refresh_field_feedback(inputs)
            _update_placement_visibility(inputs)
            session=Session();session.inputs=inputs;session.command=command
            _refresh_preset_choices(inputs,session.presets)
            _sessions.append(session)
            handlers=[(command.executePreview,PreviewHandler(session)),
                      (command.execute,ExecuteHandler(session)),
                      (command.destroy,DestroyHandler(session)),
                      (command.inputChanged,ChangedHandler(session)),
                      (command.validateInputs,ValidateHandler())]
            for event,handler in handlers:
                event.add(handler);_handlers.append(handler)
            if _update_checker is not None:
                _update_checker.check_on_open()
                _show_update_notice(session)
        except:
            UI.messageBox('Isogrid command setup failed:\n'+traceback.format_exc())


class PreviewHandler(adsk.core.CommandEventHandler):
    def __init__(self,session):super().__init__();self.session=session
    def notify(self,args):self.session.preview(args)


class ChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self,session):super().__init__();self.session=session
    def notify(self,args):
        if self.session.updating:return
        # Nested GroupCommandInput inputChanged events may supply the group's
        # child collection, not the whole command collection.
        inputs=getattr(self.session,'inputs',None) or args.inputs
        changed=args.input.id
        try:
            if changed in presets.FIELDS and changed not in getattr(
                    self.session,'preset_manual_membership',set()):
                # A field edited since the preset editor opened is a sensible
                # default inclusion; explicit checkbox decisions always win.
                self.session.updating=True
                try:
                    try:_preset_input(inputs,'preset_include_'+changed).value=True
                    except (KeyError,AttributeError):pass  # Legacy mock dialogs.
                finally:self.session.updating=False
            if changed=='preset_choice':
                item=_preset_input(inputs,'preset_choice').selectedItem
                name=item.name if item else ''
                if name in self.session.presets.data:
                    values=self.session.presets.get(name)
                    self.session.updating=True
                    try:
                        for key,value in values.items():
                            _set_preset_field(inputs,key,value)
                        _set_preset_inclusions(inputs,values.keys())
                        self.session.preset_manual_membership=set()
                        _preset_input(inputs,'preset_name').value=name
                    finally:
                        self.session.updating=False
                    _preset_input(inputs,'preset_status').text=(
                        f'Applied {len(values)} values from "{name}"; other settings unchanged.')
                    _update_placement_visibility(inputs)
                    self.session.invalidate_fits(inputs)
                    _refresh_field_feedback(inputs)
                    self.session.request_preview(inputs)
            elif changed=='preset_save':
                field=_preset_input(inputs,'preset_save')
                if field.value:
                    try:
                        name=_preset_input(inputs,'preset_name').value.strip()
                        values=_included_preset_values(inputs)
                        # Validate all dimensional expressions before saving.
                        for key in values:
                            if key in ADVISORY_INPUT_UNITS:
                                _input_number(inputs,key)
                        self.session.presets.put(name,values)
                        self.session.updating=True
                        try:_refresh_preset_choices(inputs,self.session.presets,name)
                        finally:self.session.updating=False
                        _preset_input(inputs,'preset_status').text=(
                            f'Saved "{name}" with {len(values)} selected values.')
                    finally:
                        self.session.updating=True
                        try:field.value=False
                        finally:self.session.updating=False
            elif changed=='preset_delete':
                field=_preset_input(inputs,'preset_delete')
                if field.value:
                    try:
                        item=_preset_input(inputs,'preset_choice').selectedItem
                        name=item.name if item else ''
                        self.session.presets.delete(name)
                        self.session.updating=True
                        try:_refresh_preset_choices(inputs,self.session.presets)
                        finally:self.session.updating=False
                        _preset_input(inputs,'preset_status').text='Deleted preset "'+name+'".'
                    finally:
                        self.session.updating=True
                        try:field.value=False
                        finally:self.session.updating=False
            elif changed.startswith('preset_include_'):
                self.session.preset_manual_membership.add(changed[len('preset_include_'):])
                return
            elif changed in ('preset_name','preset_status','preset_group','preset_fields_group'):
                return  # Preset metadata never changes the active geometry.
            elif changed=='check_update':
                try:
                    if inputs.itemById('check_update').value and _update_checker:
                        _update_checker.check_now()
                        _show_update_notice(self.session)
                finally:
                    self.session.updating=True
                    try:inputs.itemById('check_update').value=False
                    finally:self.session.updating=False
            elif changed=='install_update':
                try:
                    version = _update_checker.available() if _update_checker else None
                    if version and _update_installer and _update_installer.start(version):
                        _show_update_notice(self.session)
                finally:
                    self.session.updating=True
                    try:inputs.itemById('install_update').value=False
                    finally:self.session.updating=False
            elif changed=='auto_nodehole':
                if inputs.itemById('auto_nodehole').value:
                    try:
                        _auto_vertex_hole(inputs)
                        self.session.invalidate_fits(inputs)
                        _refresh_field_feedback(inputs)
                        self.session.request_preview(inputs)
                    finally:
                        # Auto is a one-shot button, not an ongoing constraint.
                        self.session.updating=True
                        try: inputs.itemById('auto_nodehole').value=False
                        finally: self.session.updating=False
            elif changed=='find_fits':
                if inputs.itemById('find_fits').value:
                    try:
                        self.session.run_fit(inputs)
                    finally:
                        # A button click is an action rather than a persistent mode.
                        self.session.updating=True
                        try:inputs.itemById('find_fits').value=False
                        finally:self.session.updating=False
            elif changed=='fit_choice':
                selected=inputs.itemById('fit_choice').selectedItem
                if selected and self.session.fits:
                    self.session.apply_fit(inputs,selected.index)
            elif changed in ('material_density','custom_density'):
                selected=inputs.itemById('material_density').selectedItem
                inputs.itemById('custom_density').isVisible=(
                    selected is not None and selected.name=='User')
                self.session._saved_text(inputs)
                return  # Density changes never invalidate 2D pockets.
            elif changed in ('show_preview',):
                self.session.request_preview(inputs)
            elif changed not in ('status','activity','warnings','update_notice',
                                  'check_update','install_update','saved_result'):
                # Auto Fit bounds/effort are independent of the manual pattern.
                # Clear stale candidates without disturbing the manual preview.
                if changed not in ('fit_min_pitch','fit_max_pitch',
                                   'fit_effort','fit_rotation','depth'):
                    self.session.invalidate_fits(inputs)
                if changed in ('origin_mode','alignment'):
                    _update_placement_visibility(inputs)
                try: _refresh_field_feedback(inputs)
                except Exception as exc:
                    inputs.itemById('warnings').text='⚠ '+str(exc)
                if changed not in ('fit_min_pitch','fit_max_pitch',
                                   'fit_effort','fit_rotation'):
                    self.session.request_preview(inputs)
        except Exception as error:
            if changed.startswith('preset_'):
                _preset_input(inputs,'preset_status').text='Preset: '+str(error)
                APP.log('Isogrid preset failure:\n'+traceback.format_exc())
            else:
                inputs.itemById('status').text='Auto Fit: '+str(error)
                APP.log('Isogrid Auto Fit failure:\n'+traceback.format_exc())


class ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self,args):
        # Avoid disabling OK for geometric constraints: show inline warnings,
        # and attempt execution if the user chooses. Fusion independently
        # validates malformed numeric expressions and selection requirements.
        try:
            _refresh_field_feedback(args.inputs)
        except Exception:
            # InputChanged provides the same feedback if this event is fired
            # while Fusion is constructing the command dialog.
            pass
        args.areInputsValid=True


class ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self,session):super().__init__();self.session=session
    def notify(self,args):
        try:
            self.session.clear_preview()
            preview_timing.log('fusion.execute_clicked', busy=self.session.busy)
            signature,_,_=self.session._snapshot(args.command.commandInputs)
            if self.session.cache is None or self.session.cache_signature!=signature:
                preview_timing.log('fusion.execute_rejected', reason='preview_not_ready')
                args.executeFailedMessage='Isogrid preview is not ready; adjust settings and retry.'
                return
            data=self.session.cache
            preview_timing.log('fusion.feature_create_begin')
            _create_feature(data)
            preview_timing.log('fusion.feature_create_complete')
        except Exception as error:
            args.executeFailedMessage='Isogrid failed: '+str(error)
            APP.log('Isogrid failure:\n'+traceback.format_exc())


class DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self,session):super().__init__();self.session=session
    def notify(self,args):
        preview_timing.log('fusion.destroy_event')
        self.session.dispose()
        if self.session in _sessions:_sessions.remove(self.session)


class BackgroundResultHandler(adsk.core.CustomEventHandler):
    def notify(self,args):
        preview_timing.log('fusion.custom_event_received')
        for session in list(_sessions):
            try:session.consume()
            except Exception:APP.log('Isogrid custom-event failure:\n'+traceback.format_exc())
            try:_show_update_notice(session)
            except Exception:APP.log('Isogrid update-notice failure:\n'+traceback.format_exc())


def run(context):
    global _custom_event, _update_checker, _update_installer
    preview_timing.log('fusion.addin_start', version=RUNNING_VERSION)
    try:
        # Fusion keeps imported helper modules in sys.modules across Add-In
        # Stop/Run cycles. Reload source after files are replaced on disk.
        # Compiled GEOS support is disabled; never reload its native module.
        # Reload geometry primitives first: Fusion keeps sys.modules alive
        # across Add-In Stop/Run cycles. Reloading only geometry left the old
        # curves2d implementation installed after an update (e.g. missing
        # Ellipse/Nurbs attributes). Keep all modules on the same generation.
        importlib.invalidate_caches()
        importlib.reload(exact_curves)
        importlib.reload(exact_clipper)
        importlib.reload(geometry)
        importlib.reload(manufacturability)
        importlib.reload(presets)
        importlib.reload(fast_fit)
        importlib.reload(fitting)
        importlib.reload(async_engine)
        importlib.reload(update_checker)
        # Re-registration is safe after an Add-In Stop/Run cycle.
        try: APP.unregisterCustomEvent(CUSTOM_EVENT_ID)
        except: pass
        _custom_event=APP.registerCustomEvent(CUSTOM_EVENT_ID)
        custom_handler=BackgroundResultHandler()
        _custom_event.add(custom_handler)
        _handlers.append(custom_handler)
        if _update_checker is not None:
            _update_checker.close()
        _update_checker=update_checker.UpdateChecker(
            RUNNING_VERSION,lambda: APP.fireCustomEvent(CUSTOM_EVENT_ID))
        if _update_installer is not None:
            _update_installer.close()
        _update_installer=update_checker.UpdateInstaller(
            Path(__file__).parent, lambda: APP.fireCustomEvent(CUSTOM_EVENT_ID))
        workspace=UI.workspaces.itemById(WORKSPACE_ID)
        panel=workspace.toolbarPanels.itemById(PANEL_ID)
        if panel is None:raise RuntimeError('Cannot locate the Solid > Add-Ins panel.')
        command=UI.commandDefinitions.itemById(COMMAND_ID)
        if command:command.deleteMe()
        # Fusion uses the CommandDefinition name for the dialog title as well
        # as the toolbar label. This is the version *actually loaded*.
        command=UI.commandDefinitions.addButtonDefinition(COMMAND_ID,COMMAND_TITLE,
            'Create a planar isogrid as a finishing cut; face boundaries and voids are respected.')
        handler=CreatedHandler();command.commandCreated.add(handler);_handlers.append(handler)
        control=panel.controls.itemById(COMMAND_ID)
        if control:control.deleteMe()
        control=panel.controls.addCommand(command)
        control.isPromoted=True
    except:
        UI.messageBox('Isogrid failed to start:\n'+traceback.format_exc())


def stop(context):
    global _custom_event, _update_checker, _update_installer
    if _update_installer is not None:
        _update_installer.close()
        _update_installer=None
    if _update_checker is not None:
        _update_checker.close()
        _update_checker=None
    for session in list(_sessions):session.dispose()
    try:
        ws=UI.workspaces.itemById(WORKSPACE_ID)
        panel=ws.toolbarPanels.itemById(PANEL_ID)
        control=panel.controls.itemById(COMMAND_ID)
        if control:control.deleteMe()
        definition=UI.commandDefinitions.itemById(COMMAND_ID)
        if definition:definition.deleteMe()
    finally:
        try:APP.unregisterCustomEvent(CUSTOM_EVENT_ID)
        except:pass
        _custom_event=None
        _handlers.clear();_sessions.clear()
