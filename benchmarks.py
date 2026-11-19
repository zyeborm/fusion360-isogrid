"""Compare identical full 2-D isogrid layouts on both optional backends.

Run: python benchmarks.py
The same candidates, fillets, and final CutShape pipeline are evaluated for
both backends. Preparation time is reported separately: it is paid once per
manual operation or entire optimisation search, not once per fit candidate.
"""
import math
import statistics
import time
import geometry as g


def shapes():
    square=[(0,0),(10,0),(10,10),(0,10)]
    void=[(5+1.5*math.cos(t*math.tau/64),
           5+1.5*math.sin(t*math.tau/64)) for t in range(64)]
    arc=[(7+7*math.cos(t*math.pi/64),20-7*math.sin(t*math.pi/64))
         for t in range(65)]
    complex_outer=[(0,0),(20,0),(25,8),(25,20)]+arc+[(0,0)]
    holes=[(x,y,r,n) for x,y,r,n in ((10,5,1,64),(18,11,.8,32),
                                    (8,14,1.2,64))]
    loops=[(complex_outer,True)]+[
        ([(x+r*math.cos(t*math.tau/n),y+r*math.sin(t*math.tau/n))
          for t in range(n)],False) for x,y,r,n in holes]
    return {'rectangle':g.Region([(square,True)]),
            'one circular void':g.Region([(square,True),(void,False)]),
            'arc cusp + 3 voids':g.Region(loops)}


def candidates(count=20):
    return [(i*.13,i*.05,i*7) for i in range(count)]


def run_case(region, backend, trials):
    start=time.perf_counter()
    prepared=g.PreparedGeometry([region],.2,.25,backend=backend)
    prepare_ms=(time.perf_counter()-start)*1000
    timings=[]; results=[]
    for dx,dy,rotation in trials:
        start=time.perf_counter()
        cuts=g.make_pockets([region],2,.2,.2,.25,dx,dy,rotation,.15,
                            max_cells=1000,prepared=prepared)
        timings.append((time.perf_counter()-start)*1000)
        results.append((len(cuts),sum(sum(g.area(p) for p in cut.loops)
                                      for cut in cuts)))
    return prepare_ms,statistics.mean(timings),statistics.median(timings),results


def main():
    trials=candidates()
    print('Measured work: full 2-D cut layout, identical candidate positions')
    print('Backend availability:',g.geometry_backend())
    for name,region in shapes().items():
        print('\n'+name)
        output={}
        for backend in ('python','geos'):
            try:
                prep,mean,median,result=run_case(region,backend,trials)
            except RuntimeError as error:
                print(f'  {backend:7}: unavailable ({error})')
                continue
            output[backend]=result
            print(f'  {backend:7}: prepare={prep:8.1f} ms, '
                  f'mean/layout={mean:7.2f} ms, median={median:7.2f} ms')
        if len(output)==2:
            deltas=[abs(a[1]-b[1])/max(abs(b[1]),1e-9)*100
                    for a,b in zip(output['python'],output['geos'])]
            print(f'  Pocket area deviation: mean={statistics.mean(deltas):.3f}% '
                  f'max={max(deltas):.3f}% '
                  '(backends use different rounded buffer approximations)')


if __name__=='__main__':main()
