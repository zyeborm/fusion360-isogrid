"""Measure unchanged v0.8.8 Python startup with simulated Autodesk objects.

Measures imports and run() separately in fresh CPython processes; this does
not include native Fusion interpreter/API startup or the Fusion UI thread.
"""
from pathlib import Path
import json
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROBE = r"""
import importlib.util, json, pathlib, sys, time, types

root=pathlib.Path.cwd()
sys.path.insert(0,str(root))

adsk=types.ModuleType('adsk')
core=types.ModuleType('adsk.core')
fusion=types.ModuleType('adsk.fusion')
for name in ('CommandCreatedEventHandler','CommandEventHandler',
             'InputChangedEventHandler','ValidateInputsEventHandler',
             'CustomEventHandler'):
    setattr(core,name,type(name,(),{}))
class FakeItem:
    def __init__(self):
        self.commandCreated=self
        self.controls=self
        self.toolbarPanels=self
        self.workspaces=self
        self.commandDefinitions=self
    def itemById(self,key):
        return None if key=='fusion360_isogrid_create' else self
    def addButtonDefinition(self,*args):return FakeItem()
    def addCommand(self,*args):return FakeItem()
    def add(self,*args):pass
    def deleteMe(self):pass
    def messageBox(self,*args):
        raise RuntimeError('Fusion addin reported error: '+str(args))
class FakeApp:
    def __init__(self):
        self.userInterface=FakeItem()
    def unregisterCustomEvent(self,*a):pass
    def registerCustomEvent(self,*a):return FakeItem()
    def fireCustomEvent(self,*a):pass
    def log(self,*a):pass
app=FakeApp()
class Application:
    @staticmethod
    def get():return app
core.Application=Application
adsk.core=core
adsk.fusion=fusion
sys.modules.update({'adsk':adsk,'adsk.core':core,'adsk.fusion':fusion})

spec=importlib.util.spec_from_file_location('fusion360_isogrid_startup',root/'fusion360-isogrid.py')
mod=importlib.util.module_from_spec(spec)
t0=time.perf_counter_ns()
spec.loader.exec_module(mod)
t1=time.perf_counter_ns()
mod.run({})
t2=time.perf_counter_ns()
mod.stop({})
t3=time.perf_counter_ns()
# Startup costs after Fusion imports and first run have warmed Python modules.
mod.run({})
t4=time.perf_counter_ns()
print(json.dumps({'import_ms':(t1-t0)/1e6,
                  'first_run_ms':(t2-t1)/1e6,
                  'stop_ms':(t3-t2)/1e6,
                  'second_run_ms':(t4-t3)/1e6,
                  'total_first_ms':(t2-t0)/1e6,
                  'modules_loaded':len(sys.modules)}))
"""

def main():
    print('Benchmark: unmodified v0.8.8, CPython',sys.version.split()[0],
          'on',sys.platform,flush=True)
    records=[]
    for i in range(24):
        proc=subprocess.run([sys.executable,'-c',PROBE],
            cwd=ROOT,text=True,capture_output=True)
        if proc.returncode:
            raise RuntimeError(f'Probe {i} failed:\\n{proc.stderr}\\n{proc.stdout}')
        records.append(json.loads(proc.stdout.strip().splitlines()[-1]))
    for key in ('import_ms','first_run_ms','total_first_ms','second_run_ms','stop_ms'):
        vals=sorted(r[key] for r in records)
        print(f'{key}: median={statistics.median(vals):.2f} ms; '
              f'min={vals[0]:.2f} ms; p95={vals[22]:.2f} ms; '
              f'max={vals[-1]:.2f} ms',flush=True)
    print('Loaded modules:',records[0]['modules_loaded'])

if __name__ == '__main__':
    main()
