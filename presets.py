"""Sparse, user-named parameter presets; independent of Autodesk APIs.

Values are expressions (where applicable), not their evaluated numerical values.
The JSON is user data, written atomically outside the add-in installation.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

VERSION = 1
EXPRESSION_FIELDS = (
    'pitch','rib','depth','perimeter','holeclear','dx','dy','angle',
    'corner','nodehole','minfraction','tool_diameter','min_web',
    'min_pocket','stock_thickness','min_skin','fit_min_pitch','fit_max_pitch',
)
BOOL_FIELDS = ('trim_boundary','fit_rotation')
CHOICE_FIELDS = ('anchor','fit_effort')
FIELDS = EXPRESSION_FIELDS + BOOL_FIELDS + CHOICE_FIELDS
LABELS = {
    'pitch':'Cell pitch','rib':'Rib width','depth':'Extrusion depth',
    'perimeter':'Perimeter margin','holeclear':'Void clearance',
    'dx':'X start offset','dy':'Y start offset','angle':'Grid rotation',
    'corner':'Pocket corner radius','nodehole':'Vertex hole diameter',
    'minfraction':'Minimum pocket area (%)','tool_diameter':'Cutter diameter',
    'min_web':'Minimum material web','min_pocket':'Minimum usable pocket diameter',
    'stock_thickness':'Material thickness','min_skin':'Minimum remaining skin',
    'fit_min_pitch':'Auto Fit minimum pitch','fit_max_pitch':'Auto Fit maximum pitch',
    'trim_boundary':'Trim to boundary / voids','fit_rotation':'Search rotations',
    'anchor':'Grid anchor','fit_effort':'Auto Fit effort',
}


def default_path():
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or (Path.home()/'AppData'/'Roaming'))
    elif sys.platform == 'darwin':
        base = Path.home()/'Library'/'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')
    return base/'fusion360-isogrid'/'presets.json'


def validate_fields(fields):
    if not isinstance(fields, dict) or not fields:
        raise ValueError('Select at least one value for a preset.')
    if len(fields)>len(FIELDS):
        raise ValueError('Too many fields in preset.')
    for key,value in fields.items():
        if key not in FIELDS:raise ValueError('Unsupported preset field: '+str(key))
        if key in BOOL_FIELDS:
            if type(value) is not bool:raise ValueError('Expected a checkbox for '+key)
        elif not isinstance(value,str) or not value.strip() or len(value)>512:
            raise ValueError('Expected an expression/selection for '+key)
    return dict(fields)


class Store:
    def __init__(self, path=None):
        self.path=Path(path) if path is not None else default_path()
        self.data={}
        self.reload()

    def reload(self):
        try:
            with self.path.open('r',encoding='utf-8') as f:payload=json.load(f)
        except FileNotFoundError:
            self.data={}
            return
        if not isinstance(payload,dict) or payload.get('version') != VERSION:
            raise ValueError('Unsupported preset file format.')
        src=payload.get('presets',{})
        if not isinstance(src,dict):raise ValueError('Invalid preset collection.')
        self.data={}
        for name,fields in src.items():
            self._name(name)
            self.data[name]=validate_fields(fields)

    @staticmethod
    def _name(name):
        if not isinstance(name,str) or not name.strip() or len(name)>80:
            raise ValueError('Preset name must contain 1–80 characters.')
        if any(ord(c)<32 for c in name):
            raise ValueError('Preset name contains a control character.')

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.presets-',suffix='.tmp',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump({'version':VERSION,'presets':self.data},f,
                          indent=2,sort_keys=True,ensure_ascii=False)
                f.write('\n');f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def put(self,name,fields):
        self._name(name)
        values=validate_fields(fields)
        self.data[name.strip()]=values
        self._save()

    def delete(self,name):
        if name not in self.data:raise ValueError('Select a saved preset to delete.')
        del self.data[name]
        self._save()

    def names(self):return sorted(self.data,key=str.casefold)

    def get(self,name):return dict(self.data[name])
