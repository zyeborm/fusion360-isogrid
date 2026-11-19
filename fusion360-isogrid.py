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
import html
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import geometry
import fitting
import async_engine
import update_checker

APP = adsk.core.Application.get()
UI = APP.userInterface
COMMAND_ID = 'fusion360_isogrid_create'
COMMAND_NAME = 'fusion360-isogrid'
PANEL_ID = 'SolidScriptsAddinsPanel'
WORKSPACE_ID = 'FusionSolidEnvironment'
ATTRIBUTE_GROUP = 'fusion360-isogrid'
CUSTOM_EVENT_ID = 'fusion360_isogrid_worker_9b70f5e1'
_handlers = []
_sessions = []
_custom_event = None
_update_checker = None
_update_installer = None


def _installed_version():
    with open(Path(__file__).with_suffix('.manifest'), encoding='utf-8') as file:
        return str(json.load(file)['version'])


def _show_update_notice(session):
    """Sync update notice/button from worker state on Fusion's UI thread."""
    if not session.alive or session.inputs is None or _update_checker is None:
        return
    notice = session.inputs.itemById('update_notice')
    button = session.inputs.itemById('install_update')
    if notice is None or button is None:
        return
    newer = _update_checker.available()
    state = (_update_installer.state() if _update_installer is not None
             else ('idle', None, None))
    token = (newer, state)
    if getattr(session, '_shown_update', None) == token:
        return
    session._shown_update = token
    status, version, error = state
    if status == 'installed':
        notice.formattedText = (
            f'<b>Isogrid {html.escape(version)} installed.</b> '
            'Restart Fusion to use the updated add-in.')
        notice.isVisible = True
        button.isVisible = False
    elif status == 'working':
        notice.formattedText = (
            f'Installing Isogrid {html.escape(version)}…')
        notice.isVisible = True
        button.isVisible = False
    elif newer:
        detail = (f'Previous installation attempt failed: {html.escape(error)}. '
                  if status == 'error' and error else '')
        notice.formattedText = (detail +
            f'<b>Isogrid {html.escape(newer)} is available.</b> '
            'Install directly from GitHub?')
        notice.isVisible = True
        button.isVisible = True
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


def _face_region(face,frame,tolerance):
    loops=[]
    for i in range(face.loops.count):
        loop=face.loops.item(i)
        samples=[_strokes(loop.coEdges.item(k).edge.evaluator,tolerance)
                 for k in range(loop.coEdges.count)]
        poly=_sequence(samples,frame)
        loops.append((poly,bool(loop.isOuter)))
    return geometry.Region(loops)


def _profile_region(profile,frame,tolerance):
    loops=[]
    for i in range(profile.profileLoops.count):
        loop=profile.profileLoops.item(i)
        samples=[]
        for j in range(loop.profileCurves.count):
            ent=loop.profileCurves.item(j).sketchEntity
            curve=ent.worldGeometry
            samples.append(_strokes(curve.evaluator,tolerance))
        loops.append((_sequence(samples,frame),bool(loop.isOuter)))
    return geometry.Region(loops)


def _inputs_to_settings(inputs):
    ids=('pitch','rib','depth','perimeter','holeclear','dx','dy','angle',
         'corner','nodehole','minfraction')
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
        if hole>diameter_limit+1e-7:
            messages.append(
                f'Vertex hole diameter exceeds the nominal rounded-junction maximum '
                f'({diameter_limit*10:.3g} mm = 2 × (rib width + corner radius)); '
                'circles may overlap triangular pockets.')
        elif abs(hole-diameter_limit)<=1e-7:
            messages.append('Vertex hole is tangent to the rounded pockets; '
                            'zero clearance may create coincident sketch profiles.')
    if hole<0:messages.append('Vertex-hole diameter must be non-negative.')
    if s['depth']<=0:messages.append('Extrusion depth must be positive for a cut.')
    for field,title in [('perimeter','Perimeter margin'),('holeclear','Void clearance'),
                        ('corner','Corner radius')]:
        if s[field]<0:messages.append(f'{title} must be non-negative.')
    if not 0<=s['minfraction']<=100:
        messages.append('Minimum pocket area must be in the 0–100% range.')
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
    face,profile=_selected(inputs)
    s=_inputs_to_settings(inputs)
    _validate_settings(s)
    # Sample curved boundaries to <= 0.025 mm or 1/8 of rib width.
    tolerance=max(0.0005,min(0.0025,s['rib']/8))
    source_key=(face.entityToken,profile.entityToken if profile else None,tolerance)
    if cache is not None and cache.get('key')==source_key:
        frame,regions=cache['frame'],cache['regions']
    else:
        frame=FaceFrame(face)
        face_region=_face_region(face,frame,tolerance)
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
    return face,profile,frame,s,regions,origin,rotation


def _compute(inputs,max_cells=1600,source_cache=None):
    face,profile,frame,s,regions,origin,rotation=_source_geometry(inputs,source_cache)
    outlines=geometry.make_pockets(regions,s['pitch'],s['rib'],s['perimeter'],
        s['holeclear'],s['dx'],s['dy'],rotation,s['corner'],
        s['minfraction']/100,max_cells=max_cells,
        vertex_hole_diameter=s['nodehole'],base_origin=origin,
        anchor='triangle' if s['anchor']=='Triangle centre' else 'vertex',
        backend=s['backend'],trim_boundary=s['trim_boundary'])
    if not outlines:raise ValueError('No pockets fit this region. Reduce margins or cell pitch.')
    return face,profile,frame,s,regions,outlines


def _draw_preview(session,data):
    session.clear_preview()
    face,profile,frame,settings,regions,outlines=data
    component=face.body.parentComponent
    graphics=component.customGraphicsGroups.add()
    session.graphics=graphics
    coords=[]
    for shape in outlines:
        for poly in shape.loops:
            for a,b in zip(poly,poly[1:]+poly[:1]):
                for uv in (a,b):
                    pt=frame.to_world(uv,lift=0.006)
                    coords.extend([pt.x,pt.y,pt.z])
    if not coords:return
    obj=graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(coords),[],False)
    obj.weight=2
    obj.color=adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(12,171,235,255))
    APP.activeViewport.refresh()


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
        lines=sketch.sketchCurves.sketchLines
        circles=sketch.sketchCurves.sketchCircles
        sketch.isComputeDeferred=True
        for shape in outlines:
            if shape.circle:
                center,radius=shape.circle
                center_pt=sketch.modelToSketchSpace(frame.to_world(center))
                circles.addByCenterRadius(center_pt,radius)
                continue
            for poly in shape.loops:
                for a,b in zip(poly,poly[1:]+poly[:1]):
                    p1=sketch.modelToSketchSpace(frame.to_world(a))
                    p2=sketch.modelToSketchSpace(frame.to_world(b))
                    lines.addByTwoPoints(p1,p2)
        sketch.isComputeDeferred=False
        # Determine which Fusion profiles correspond to pockets, not protected
        # islands or the exterior. Their sample point is in sketch coordinates.
        candidates=[]
        for shape in outlines:
            if not settings['trim_boundary']:
                # Keep the entire cell in the generated sketch, but omit
                # profiles that have zero intersection with the target face.
                # Other outside portions remain available for manual trimming.
                fragments=geometry.clip_pocket(shape.outline,regions)
                if sum(geometry.area(poly) for poly in fragments)<=1e-8:
                    continue
            candidates.append((geometry.bounds(shape.outline),shape.loops))
        chosen=adsk.core.ObjectCollection.create()
        for i in range(sketch.profiles.count):
            item=sketch.profiles.item(i)
            in_sketch=item.face.pointOnFace
            xy=frame.to_xy(sketch.sketchToModelSpace(in_sketch))
            if settings['trim_boundary'] and not all(region.contains(xy) for region in regions):continue
            if any(geometry.boxes_overlap(box,(xy[0],xy[1],xy[0],xy[1])) and
                   sum(1 if geometry.area(loop)>0 else -1
                       for loop in loops if geometry.in_poly(xy,loop,False))>0
                   for box,loops in candidates):
                chosen.add(item)
        if chosen.count==0:raise RuntimeError('Fusion produced no usable pocket profiles.')
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
        # Keep a record of the choices for inspection/re-use in future builds.
        saved=dict(settings)
        saved['faceToken']=source_face_token
        saved['sketchProfileToken']=source_profile_token
        saved['schemaVersion']=7
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
        self.snapshot = None
        self.worker = async_engine.LatestWorker(
            lambda: APP.fireCustomEvent(CUSTOM_EVENT_ID))

    def dispose(self):
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

    def request_preview(self, inputs, force=False):
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
            signature,model,payload=self._snapshot(inputs)
            if not force and signature==self.last_signature:
                if self.cache_signature==signature:
                    # A depth-only edit reuses the existing pocket geometry.
                    self.cache[3].update(depth=payload['settings']['depth'],
                        depth_expression=payload['settings']['depth_expression'])
                    if not inputs.itemById('show_preview').value:
                        self.clear_preview()
                return
            self.last_signature=signature
            self.cache=None
            self.cache_signature=None
            self.clear_preview()   # Prevent stale outlines being mistaken for current geometry.
            self.snapshot=(signature,model,payload)
            self.busy=True
            self.fit_running=False
            self.pending_kind='preview'
            self.revision=self.worker.submit('preview',payload)
            self._activity('working','Computing preview')
            inputs.itemById('status').text='Computing 2D pockets…'
        except Exception as error:
            self.worker.cancel()
            self.busy=False;self.fit_running=False
            self.pending_kind=None
            self.last_signature=None
            self.cache=None;self.cache_signature=None
            self.clear_preview()
            self._activity('error',str(error))
            inputs.itemById('status').text='Preview: '+str(error)

    def preview(self,args):
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
        if not self.command.doExecutePreview():
            APP.log('Isogrid could not request a new executePreview transaction.')

    def _preview_text(self,inputs,data):
        _,_,_,_,_,outlines=data
        total=sum(len(shape.loops) for shape in outlines)
        holes=sum(shape.circle is not None for shape in outlines)
        _refresh_field_feedback(inputs,outlines)
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
            self.fit_summary=(f'Fit: {fit.label} · {fit.area*100:.1f} mm² removed · '
                f'{fit.partials} partial pockets · {fit.slivers} small pockets. ')
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
            if kind=='progress':
                if self.fit_running:
                    self._activity('working',f'Auto Fit {message["done"]}/{message["total"]}')
                continue
            if kind=='error':
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
                               f'{candidate.area*100:.0f} mm² · {candidate.partials} partial')
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
                'nodehole':('Vertex hole diameter (0 = off)','0 mm','mm'),
                'minfraction':('Minimum pocket area (%)','5',''),
            }
            for key,(title,value,units) in defaults.items():
                if key in ADVISORY_INPUT_UNITS:
                    inputs.addStringValueInput(key,title,value)
                else:
                    vi=(adsk.core.ValueInput.createByString(value) if units
                        else adsk.core.ValueInput.createByReal(5))
                    inputs.addValueInput(key,title,units,vi)
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
            inputs.addBoolValueInput('show_preview','Show outline preview',True,'',True)
            inputs.addTextBoxCommandInput('activity','Geometry worker',
                '<span style="color:#888888;"><b>● Idle</b></span> — Select a face',1,True)
            inputs.addTextBoxCommandInput('status','Pattern','Select a planar face to preview.',3,True)
            inputs.addTextBoxCommandInput('warnings','Geometry warnings',
                'No geometric warnings.',5,True)
            notice=inputs.addTextBoxCommandInput('update_notice','Update','',2,True)
            notice.isVisible=False
            button=inputs.addBoolValueInput('install_update','Install Update',False,'',False)
            button.isVisible=False
            _refresh_field_feedback(inputs)
            _update_placement_visibility(inputs)
            session=Session();session.inputs=inputs;session.command=command
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
        inputs=args.inputs
        changed=args.input.id
        try:
            if changed=='install_update':
                try:
                    version = _update_checker.available() if _update_checker else None
                    if version and _update_installer and _update_installer.start(version):
                        _show_update_notice(self.session)
                finally:
                    self.session.updating=True
                    try:inputs.itemById('install_update').value=False
                    finally:self.session.updating=False
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
            elif changed in ('show_preview',):
                self.session.request_preview(inputs)
            elif changed not in ('status','activity','warnings','update_notice','install_update'):
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
            signature,_,_=self.session._snapshot(args.command.commandInputs)
            if self.session.cache is not None and self.session.cache_signature==signature:
                data=self.session.cache
            else:
                # Rare fast-click fallback, when OK precedes the worker result.
                data=_compute(args.command.commandInputs,max_cells=1600,
                              source_cache=self.session.source_cache)
            _create_feature(data)
        except Exception as error:
            args.executeFailedMessage='Isogrid failed: '+str(error)
            APP.log('Isogrid failure:\n'+traceback.format_exc())


class DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self,session):super().__init__();self.session=session
    def notify(self,args):
        self.session.dispose()
        if self.session in _sessions:_sessions.remove(self.session)


class BackgroundResultHandler(adsk.core.CustomEventHandler):
    def notify(self,args):
        for session in list(_sessions):
            try:session.consume()
            except Exception:APP.log('Isogrid custom-event failure:\n'+traceback.format_exc())
            try:_show_update_notice(session)
            except Exception:APP.log('Isogrid update-notice failure:\n'+traceback.format_exc())


def run(context):
    global _custom_event, _update_checker, _update_installer
    try:
        # Fusion keeps imported helper modules in sys.modules across Add-In
        # Stop/Run cycles. Reload source after files are replaced on disk.
        # Compiled GEOS support is disabled; never reload its native module.
        importlib.reload(geometry)
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
            _installed_version(),lambda: APP.fireCustomEvent(CUSTOM_EVENT_ID))
        if _update_installer is not None:
            _update_installer.close()
        _update_installer=update_checker.UpdateInstaller(
            Path(__file__).parent, lambda: APP.fireCustomEvent(CUSTOM_EVENT_ID))
        workspace=UI.workspaces.itemById(WORKSPACE_ID)
        panel=workspace.toolbarPanels.itemById(PANEL_ID)
        if panel is None:raise RuntimeError('Cannot locate the Solid > Add-Ins panel.')
        command=UI.commandDefinitions.itemById(COMMAND_ID)
        if command:command.deleteMe()
        command=UI.commandDefinitions.addButtonDefinition(COMMAND_ID,COMMAND_NAME,
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
