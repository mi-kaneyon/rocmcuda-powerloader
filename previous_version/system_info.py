#!/usr/bin/env python3
import subprocess
import platform
import re
import torch

def get_cpu_info():
    """
    lscpu コマンド等を使って CPU 情報を取得し、
    脆弱性関連行 (Vulnerability ...) は表示しないようにする例。
    """
    try:
        output = subprocess.check_output(["lscpu"], stderr=subprocess.STDOUT, universal_newlines=True)
        lines = output.strip().splitlines()
        filtered_lines = []
        for line in lines:
            # 'Vulnerability' を含む行を除外する
            if "Vulnerability" in line:
                continue
            filtered_lines.append(line)
        return "\n".join(filtered_lines)
    except Exception as e:
        return f"CPU Info error: {e}"

def get_gpu_info():
    """
    ROCm 環境か CUDA(NVIDIA) 環境かを判別して GPU 情報を取得。
    - ROCm → rocm-smi
    - CUDA → nvidia-smi
    - どちらでもない場合は "No GPU or unknown environment" とする。
    """
    # ROCm 判定
    if hasattr(torch.version, 'hip') and torch.version.hip is not None:
        # ROCm 環境
        try:
            # rocm-smi のバージョンによりオプションが異なるかもしれないので注意
            # 例として temp と usage を取る
            cmd = ["rocm-smi", "--showtemp", "--showmemuse", "--showuse"]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
            return f"ROCm GPU Info:\n{output}"
        except Exception as e:
            return f"ROCm GPU Info error: {e}"
    # CUDA 判定
    elif torch.version.cuda is not None:
        # NVIDIA CUDA 環境
        try:
            cmd = [
                "nvidia-smi",
                "--format=csv,noheader,nounits",
                "--query-gpu=utilization.gpu,utilization.memory,memory.total,memory.free,memory.used"
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
            # 例としてそのまま返す
            return f"NVIDIA GPU Info:\n{output}"
        except Exception as e:
            return f"NVIDIA GPU Info error: {e}"
    else:
        # どちらでもない
        return "No GPU or unknown environment"

def get_psu_power():
    """
    PSU Power (消費電力) 表示の例。
    CUDA 環境 → nvidia-smi で Power Draw 取得
    ROCm 環境 → rocm-smi で平均消費電力 (AvgPwr) 等を取得
    """
    # ROCm 判定
    if hasattr(torch.version, 'hip') and torch.version.hip is not None:
        try:
            # rocm-smi --showpower など
            cmd = ["rocm-smi", "--showpower"]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
            # 必要に応じてパース
            return f"PSU Power (ROCm):\n{output}"
        except Exception as e:
            return f"PSU Power (ROCm) error: {e}"
    elif torch.version.cuda is not None:
        try:
            # nvidia-smi で Power Draw を取得
            cmd = [
                "nvidia-smi",
                "--format=csv,noheader,nounits",
                "--query-gpu=power.draw"
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
            return f"PSU Power (CUDA): {output.strip()} W"
        except Exception as e:
            return f"PSU Power (CUDA) error: {e}"
    else:
        return "No GPU environment - PSU power unknown"
