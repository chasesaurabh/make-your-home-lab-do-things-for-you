"""Download the exact locked model files, or verify an existing download.

Weights are separately licensed. No token, account or remote Python code is used.
Existing verified files are reused; incomplete or mismatched files require inspection.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from model_assets import profile,artifact_path,verify_file,verify_directory

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile",choices=["2b","9b","27b","122b"])
    parser.add_argument("--destination",type=Path,required=True)
    parser.add_argument("--verify-only",action="store_true")
    args=parser.parse_args()
    _,config=profile(args.profile)
    root=args.destination.resolve()
    if args.verify_only:
        print(json.dumps(verify_directory(root,config),indent=2));return
    root.mkdir(parents=True,exist_ok=True)
    for item in config["files"]:
        target=artifact_path(root,item["path"])
        if target.exists():
            verify_file(target,item)
            print("Verified existing "+item["path"],flush=True);continue
        partial=target.with_name(target.name+".partial")
        if partial.exists():
            raise ValueError("Incomplete download exists; inspect it or choose a fresh destination: "+item["path"])
        target.parent.mkdir(parents=True,exist_ok=True)
        url=f"https://huggingface.co/{config['repository']}/resolve/{config['revision']}/{quote(item['path'],safe='/')}"
        print("Downloading "+item["path"]+f" ({item['bytes']} bytes)",flush=True)
        with urlopen(url,timeout=120) as response,partial.open("xb") as output:
            while block:=response.read(8*1024*1024):output.write(block)
        verify_file(partial,item)
        partial.replace(target)
    result=verify_directory(root,config)
    result["verified_utc"]=datetime.now(timezone.utc).isoformat()
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
