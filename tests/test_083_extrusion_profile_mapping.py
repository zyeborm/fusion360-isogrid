"""Prevent silent loss of preview triangles when mapping to Fusion profiles.

The native sketch profile's arbitrary sample point was formerly retested
against sampled outline polygons; this could reject a legitimate closed
profile. A generated sketch curve and its outer ProfileLoop identify ownership
without geometric reclassification.
"""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_preview_lifecycle import load_fusion_ui


class Collection:
    def __init__(self,entries):self.entries=entries
    @property
    def count(self):return len(self.entries)
    def item(self,i):return self.entries[i]


def loop(tokens, outer=True):
    def entity(owner):
        return NS(attributes=NS(itemByName=lambda group,key:
                  NS(value=owner) if owner is not None else None))
    return NS(isOuter=outer,profileCurves=Collection([
        NS(sketchEntity=entity(t)) for t in tokens]))


def profile(*loops):
    # The previous algorithm relied on pointOnFace. Deliberately omit it.
    return NS(profileLoops=Collection(list(loops)))


class ExtrusionProfileMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.ui=load_fusion_ui()

    def test_valid_closed_profiles_are_kept_regardless_of_sample_point(self):
        sketch=NS(profiles=Collection([
            profile(loop(['0:0']*3)),
            profile(loop(['1:0']*3),loop(['1:1'],False)),
            profile(loop(['1:1'])), # Protected island must remain material.
        ]))
        result=self.ui._match_generated_profiles(sketch,{'0:0','1:0'})
        self.assertIs(result[0],sketch.profiles.item(0))
        self.assertIs(result[1],sketch.profiles.item(1))
        self.assertEqual(len(result),2)

    def test_missing_sketch_profile_cannot_silently_drop_a_pocket(self):
        sketch=NS(profiles=Collection([profile(loop(['0:0']*3))]))
        report={}
        result=self.ui._match_generated_profiles(sketch,{'0:0','1:0'},report=report)
        self.assertEqual(len(result),1)
        self.assertEqual(report['missing'],['1:0'])

    def test_fusion_merged_two_pocket_boundaries_fails_closed(self):
        sketch=NS(profiles=Collection([profile(loop(['0:0','0:0','1:0']))]))
        report={}
        result=self.ui._match_generated_profiles(sketch,{'0:0','1:0'},report=report)
        self.assertEqual(len(result),0)
        self.assertEqual(report['missing'],['0:0','1:0'])

    def test_unbounded_surrounding_profile_is_excluded(self):
        sketch=NS(profiles=Collection([profile(loop(['99:0'])),
                                       profile(loop(['0:0']*3))]))
        chosen=self.ui._match_generated_profiles(sketch,{'0:0'})
        self.assertEqual(chosen,[sketch.profiles.item(1)])

    def test_recomputed_fusion_profiles_with_missing_entity_tags_use_native_geometry(self):
        # An actual Fusion ProfileCurve may refer to a regenerated curve with
        # no attribute. Its interior profile point is still available. Check
        # it against the exact native output, rather than a sampled polygon.
        curves=self.ui.exact_curves
        tri=[curves.Line((0,0),(1,0)),curves.Line((1,0),(0,1)),
             curves.Line((0,1),(0,0))]
        p=profile(loop([None,None,None]))
        p.face=NS(pointOnFace=(.2,.2))
        sketch=NS(profiles=Collection([p]),sketchToModelSpace=lambda point:point)
        frame=NS(to_xy=lambda point:point)
        report={}
        result=self.ui._match_generated_profiles(sketch,{'0:0'},frame,
            {'0:0':((0.,0.,1.,1.),tri,[],None)},report)
        self.assertEqual(result,[p])
        self.assertEqual(report['matched'],1)
        self.assertEqual(report['fallback'],1)

    def test_bad_profile_point_cannot_select_unrelated_area(self):
        curves=self.ui.exact_curves
        tri=[curves.Line((0,0),(1,0)),curves.Line((1,0),(0,1)),
             curves.Line((0,1),(0,0))]
        p=profile(loop([None,None,None]))
        p.face=NS(pointOnFace=(.9,.9))
        sketch=NS(profiles=Collection([p]),sketchToModelSpace=lambda point:point)
        report={}
        result=self.ui._match_generated_profiles(sketch,{'0:0'},
            NS(to_xy=lambda point:point),
            {'0:0':((0.,0.,1.,1.),tri,[],None)},report)
        self.assertEqual(result,[])
        self.assertEqual(report['missing'],['0:0'])


if __name__=='__main__':unittest.main()

class FeatureIntegrationTests(unittest.TestCase):
    """Exercise actual _create_feature and extrude selected profiles, no SDK."""
    @classmethod
    def setUpClass(cls):cls.ui=load_fusion_ui()

    def test_two_full_triangles_and_drilled_circle_are_selected(self):
        from unittest.mock import patch
        import types
        geometry=self.ui.geometry
        curves=self.ui.exact_curves

        token_counter=[0]
        created=[]
        def native_entity(*args):
            token_counter[0]+=1
            token='curve'+str(token_counter[0])
            created.append(token)
            return owner_entity(token)
        def circle_entity(*args):
            token_counter[0]+=1
            token='circle'+str(token_counter[0])
            created.append(token)
            return owner_entity(token)
        tagged={}
        def owner_entity(token):
            def add(group,key,value):tagged[token]=value
            return NS(attributes=NS(add=add))

        skcurves=NS(sketchLines=NS(addByTwoPoints=native_entity),
                    sketchCircles=NS(addByCenterRadius=circle_entity))
        profile_list=Collection([])
        class Sketch:
            name='';isVisible=True
            sketchCurves=skcurves
            profiles=profile_list
            attributes=NS(add=lambda *a:None)
            xDirection=NS(crossProduct=lambda y:NS(dotProduct=lambda z:1.))
            yDirection=object()
            def modelToSketchSpace(self,p):return p
            @property
            def isComputeDeferred(self):return self._deferred
            @isComputeDeferred.setter
            def isComputeDeferred(self,value):
                self._deferred=value
                if not value:
                    # Exactly one Fusion profile for each of 2 triangles and
                    # one vertex hole. Each token comes from the native output.
                    self.profiles.entries=[
                        profile(loop([tagged[t] for t in created[0:3]])),
                        profile(loop([tagged[t] for t in created[3:6]])),
                        profile(loop([tagged[t] for t in created[6:7]]))]
            def deleteMe(self):raise AssertionError('Unexpected rollback')
        sketch=Sketch()
        inserted=[]
        class Extrudes:
            def createInput(self,selected,operation):
                inserted.extend(selected)
                return NS(setOneSideExtent=lambda *a:None,
                          participantBodies=None)
            def add(self,p):return NS(name='',attributes=NS(add=lambda *a:None))
        comp=NS(sketches=NS(addWithoutEdges=lambda face:sketch),
                features=NS(extrudeFeatures=Extrudes()))
        body=NS(parentComponent=comp)
        face=NS(body=body,entityToken='source')
        frame=NS(to_world=lambda p:NS(x=p[0],y=p[1],z=0.),n=object())
        triangles=[[(0,0),(1,0),(0,1)],[(2,0),(3,0),(2,1)]]
        shapes=[geometry.CutShape(p,[p],curve_loops=[[
            curves.Line(p[i],p[(i+1)%3]) for i in range(3)]])
            for p in triangles]
        hole=geometry.circle_polygon((4.,1.),.2)
        shapes.append(geometry.CutShape(hole,[hole],circle=((4.,1.),.2)))
        core=self.ui.adsk.core
        fusion=self.ui.adsk.fusion
        class Obj(list):
            @staticmethod
            def create():return Obj()
            def add(self,obj):self.append(obj)
            @property
            def count(self):return len(self)
        with patch.object(core,'ObjectCollection',Obj,create=True), \
             patch.object(core,'ValueInput',NS(createByString=lambda x:x),create=True), \
             patch.object(fusion,'FeatureOperations',NS(CutFeatureOperation=0),create=True), \
             patch.object(fusion,'DistanceExtentDefinition',NS(create=lambda x:x),create=True), \
             patch.object(fusion,'ExtentDirections',NS(NegativeExtentDirection=1,
                   PositiveExtentDirection=2),create=True), \
             patch.object(self.ui,'APP',NS(log=lambda msg:None)):
            self.ui._create_feature((face,None,frame,
                {'trim_boundary':True,'depth_expression':'2 mm'},[],shapes))
        self.assertEqual(len(inserted),3)
        self.assertEqual(inserted,profile_list.entries)
