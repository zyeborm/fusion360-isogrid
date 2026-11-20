"""Run visual fitting cases in isolated processes and combine their images."""
from __future__ import annotations
import concurrent.futures
import csv
from pathlib import Path
import subprocess
import sys
from PIL import Image

STUDY=Path(__file__).with_name('visual_fit_study.py')
DEST=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/mnt/data')
BUDGET=int(sys.argv[2]) if len(sys.argv)>2 else 160
DEST.mkdir(parents=True,exist_ok=True)


def run(index):
    path=DEST/f'isogrid_study_case_{index+1:02}'
    path.mkdir(exist_ok=True)
    command=[sys.executable,str(STUDY),str(path),str(BUDGET),str(index)]
    process=subprocess.run(command,text=True,capture_output=True,timeout=70)
    if process.returncode:
        raise RuntimeError(f'{index+1}: {process.stderr[-2000:]}')
    return index,path,process.stdout.strip()


if __name__=='__main__':
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(run,i) for i in range(6)]
        for task in concurrent.futures.as_completed(tasks):
            result=task.result()
            results.append(result)
            print(result[2],flush=True)
    results.sort()
    pixels=[];allrows=[]
    for _,path,_ in results:
        png=path/'isogrid_integer_fit_comparison.png'
        pixels.append(Image.open(png).convert('RGB'))
        with (path/'isogrid_integer_fit_metrics.csv').open() as f:
            allrows.extend(csv.DictReader(f))
    width=max(im.width for im in pixels)
    mosaic=Image.new('RGB',(width,sum(im.height for im in pixels)),'white')
    y=0
    for pic in pixels:
        mosaic.paste(pic,(0,y));y+=pic.height
    mosaic.save(DEST/'isogrid_integer_fit_comparison.png',optimize=True)
    with (DEST/'isogrid_integer_fit_metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=allrows[0].keys())
        writer.writeheader();writer.writerows(allrows)
    print(f'SAVED {len(results)} cases; {mosaic.width} x {mosaic.height} px')
