"""Verify locked weights and start the pinned vLLM Docker image on loopback.

Requires working Docker Linux containers with NVIDIA GPU access. This script does
not install Docker/drivers, expose a public port, replace containers or choose an
unbounded context. Stop the named container explicitly when finished.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request,build_opener,ProxyHandler

from model_assets import profile,verify_directory

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile",choices=["2b","9b","27b","122b"])
    parser.add_argument("--model-dir",type=Path,required=True)
    parser.add_argument("--name",default="automation-model")
    parser.add_argument("--port",type=int,default=18107)
    parser.add_argument("--memory-fraction",type=float,default=0.85)
    parser.add_argument("--tools",action="store_true")
    parser.add_argument("--evidence",type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,60}",args.name):parser.error("Use a short lowercase container name.")
    if not 1024<=args.port<=65535:parser.error("Use a port from1024 to65535.")
    if not 0.05<=args.memory_fraction<=0.95:parser.error("Memory fraction must leave device headroom.")
    if args.evidence.exists():parser.error("Choose a new evidence filename.")
    lock,config=profile(args.profile)
    verified=verify_directory(args.model_dir,config)
    image=lock["runtime_image"]
    if subprocess.run(["docker","container","inspect",args.name],capture_output=True).returncode==0:
        parser.error("That container exists. Inspect it; use a different name for a separate run.")
    if subprocess.run(["docker","image","inspect",image],capture_output=True).returncode:
        parser.error("Pull the pinned image first: docker pull "+image)
    root=args.model_dir.resolve(strict=True)
    alias="automation-"+args.profile
    command=["docker","run","-d","--name",args.name,"--gpus","all",
        "-p",f"127.0.0.1:{args.port}:8000","--mount",f"type=bind,source={root},target=/model,readonly",
        "-e","HF_HUB_OFFLINE=1","-e","TRANSFORMERS_OFFLINE=1",image,"/model",
        "--served-model-name",alias,"--max-model-len","4096","--max-num-seqs","1",
        "--gpu-memory-utilization",str(args.memory_fraction),"--enforce-eager",
        "--limit-mm-per-prompt",'{"image":0,"video":0}',"--kv-cache-dtype",config["kv_cache_dtype"]]
    if config["quantization"]:command += ["--quantization",config["quantization"]]
    if args.tools:command += ["--enable-auto-tool-choice","--tool-call-parser","qwen3_xml"]
    evidence=dict(started_utc=datetime.now(timezone.utc).isoformat(),artifacts=verified,
                  command=command,model_alias=alias,status="starting",port=args.port)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    def save():args.evidence.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
    save()
    evidence["container_id"]=subprocess.check_output(command,text=True).strip()
    save()
    opener=build_opener(ProxyHandler({}))
    base=f"http://127.0.0.1:{args.port}"
    started=time.monotonic()
    try:
        while time.monotonic()-started<1800:
            state=subprocess.check_output(["docker","inspect",args.name,"--format","{{.State.Status}}"],text=True).strip()
            if state!="running":raise RuntimeError("Container is "+state+"; inspect docker logs "+args.name)
            try:
                with opener.open(base+"/v1/models",timeout=3) as response:models=json.load(response)
                if alias in [m["id"] for m in models.get("data",[])]:break
            except (OSError,ValueError):pass
            time.sleep(5)
        else:raise TimeoutError("Initialization observation timed out. Container is retained; inspect it before retrying.")
        evidence["advertised_models"]=models
        payload=dict(model=alias,messages=[{"role":"user","content":"Reply with exactly READY."}],
                     max_tokens=16,temperature=0,stream=False,chat_template_kwargs={"enable_thinking":False})
        evidence["probe_request"]=payload
        request=Request(base+"/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
        with opener.open(request,timeout=120) as response:evidence["probe_response"]=json.load(response)
        answer=evidence["probe_response"]["choices"][0]["message"]["content"]
        if not isinstance(answer,str) or not answer.strip():raise ValueError("Inference returned no visible answer.")
        evidence.update(status="inference_response_received",probe_exact_match=answer.strip()=="READY")
        print(json.dumps({"url":base,"model":alias,"probe_answer":answer,"exact_match":answer.strip()=="READY",
                          "stop_command":"docker stop "+args.name},indent=2))
    except Exception as error:
        evidence.update(status="failed_inspect_retained_container",error_type=type(error).__name__,error=str(error))
        raise
    finally:
        evidence["observation_seconds"]=time.monotonic()-started
        save()

if __name__=="__main__":main()
