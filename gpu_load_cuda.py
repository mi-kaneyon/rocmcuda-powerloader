#!/usr/bin/env python3
"""
gpu_load_cuda.py
----------------
CUDA向けのGPU負荷テストモジュールです。  
OpenGL を用いた 3D 描画負荷、PyTorch の Tensor 演算負荷、VRAM 負荷を行う関数群を提供します。

このモジュールは、上位の gpu_load.py から  
CUDA環境の場合の処理として呼び出されることを想定しています。
"""

import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
import threading
import time
import numpy as np
import torch
import sys

######################################
# OpenGL 用のライティング初期化
######################################
def initialize_lighting():
    glEnable(GL_LIGHTING)
    glEnable(GL_LIGHT0)
    light_position = [10.0, 10.0, 10.0, 1.0]
    glLightfv(GL_LIGHT0, GL_POSITION, light_position)
    glLightfv(GL_LIGHT0, GL_DIFFUSE, [1.0, 1.0, 1.0, 1.0])
    glLightfv(GL_LIGHT0, GL_SPECULAR, [1.0, 1.0, 1.0, 1.0])
    glEnable(GL_COLOR_MATERIAL)

######################################
# テクスチャ読み込み
######################################
def load_texture():
    try:
        print("Loading texture...")
        texture_surface = pygame.image.load('texture.jpg')
        print("Texture loaded successfully.")
        texture_data = pygame.image.tostring(texture_surface, 'RGB', 1)
        width = texture_surface.get_width()
        height = texture_surface.get_height()

        glEnable(GL_TEXTURE_2D)
        texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture_id)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, width, height, 0,
                     GL_RGB, GL_UNSIGNED_BYTE, texture_data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)

        print(f"Texture ID generated: {texture_id}")
        return texture_id
    except pygame.error as e:
        print(f"Error loading texture: {e}")
        return None

######################################
# キューブ描画
######################################
def draw_cube():
    vertices = [
        (-1, -1, -1),
        ( 1, -1, -1),
        ( 1,  1, -1),
        (-1,  1, -1),
        (-1, -1,  1),
        ( 1, -1,  1),
        ( 1,  1,  1),
        (-1,  1,  1)
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (1, 2, 6, 5),
        (0, 3, 7, 4)
    ]
    tex_coords = [
        (0, 0),
        (1, 0),
        (1, 1),
        (0, 1)
    ]
    glBegin(GL_QUADS)
    for face in faces:
        for i, vertex in enumerate(face):
            glTexCoord2fv(tex_coords[i % len(tex_coords)])
            glVertex3fv(vertices[vertex])
    glEnd()
    error = glGetError()
    if error != GL_NO_ERROR:
        print(f"OpenGL Error (draw_cube): {gluErrorString(error)}")

######################################
# draw_rotating_shapes の定義
# ここでは、単純にキューブを回転させて描画する
######################################
def draw_rotating_shapes(texture_id, rotation_angle):
    glPushMatrix()
    glRotatef(rotation_angle, 1, 1, 1)
    # ここでキューブを描画
    draw_cube()
    glPopMatrix()
    error = glGetError()
    if error != GL_NO_ERROR:
        print(f"OpenGL Error (draw_rotating_shapes): {gluErrorString(error)}")

######################################
# (1) GPU 負荷 (OpenGL レンダリング) - CUDA版
######################################
def apply_gpu_load(load_percentage, stop_event, gpu_id):
    """
    CUDA環境向け: OpenGL を用いて3D描画負荷をかける関数です。
    stop_event がセットされるまで負荷をかけ続け、負荷終了後にウィンドウを閉じます。
    """
    pygame.init()
    screen = pygame.display.set_mode((800, 600), DOUBLEBUF | OPENGL)
    pygame.display.set_caption(f"GPU Load Test (GPU {gpu_id})")

    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(45, (800 / 600), 0.1, 50.0)
    glMatrixMode(GL_MODELVIEW)

    glEnable(GL_DEPTH_TEST)
    glDepthFunc(GL_LESS)
    initialize_lighting()
    texture_id = load_texture()
    rotation_angle = 0

    if texture_id is None:
        print("[DEBUG] Texture loading failed; proceeding without texture.")

    glClearColor(0.3, 0.3, 0.3, 1.0)

    while not stop_event.is_set():
        for event in pygame.event.get():
            if event.type == QUIT:
                print("[DEBUG] Window close event -> stopping GPU load.")
                stop_event.set()

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        gluLookAt(0.0, 0.0, 15.0,
                  0.0, 0.0, 0.0,
                  0.0, 1.0, 0.0)

        draw_rotating_shapes(texture_id, rotation_angle)
        rotation_angle += load_percentage / 10.0

        pygame.display.flip()
        glFlush()
        time.sleep(0.01)

        error = glGetError()
        if error != GL_NO_ERROR:
            print(f"OpenGL Error (main loop): {gluErrorString(error)}")

    print("[DEBUG] Exiting GPU load loop. Quitting pygame...")
    pygame.quit()
    print("[DEBUG] Pygame quit. Thread ending.")

######################################
# (2) Tensor 計算で GPU に負荷をかける (PyTorch)
######################################
def tensor_calculation(load_percentage, stop_event, gpu_id):
    torch.cuda.set_device(gpu_id)
    while not stop_event.is_set():
        a = torch.rand((8000, 8000), device='cuda')
        b = torch.rand((8000, 8000), device='cuda')
        _ = torch.matmul(a, b)
        torch.cuda.synchronize()
        time.sleep(1 / (load_percentage + 1))

def apply_gpu_tensor_load(load_percentage, stop_event, gpu_ids):
    """
    PyTorch の Tensor 演算を使ってGPUに負荷をかけます。
    各 GPU に対して個別のスレッドを起動します。
    """
    print(f"Starting GPU Tensor Load with {load_percentage}% on GPUs: {gpu_ids}")
    for gpu_id in gpu_ids:
        threading.Thread(
            target=tensor_calculation,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()

######################################
# (3) 3D 描画と Tensor 計算の複合負荷
######################################
def apply_combined_load(load_percentage, stop_event, gpu_ids):
    """
    GPU上でTensor計算とOpenGL描画を同時に実行します。
    各GPUに対して、Tensor計算とOpenGL描画用のスレッドを起動します。
    """
    for gpu_id in gpu_ids:
        threading.Thread(
            target=tensor_calculation,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()
        threading.Thread(
            target=apply_gpu_load,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()

######################################
# (4) VRAM 負荷 (動的割当)
######################################
def allocate_vram_dynamic(vram_percentage, stop_event, gpu_id):
    """
    ユーザーが指定したvram_percentage(%)に合わせて、VRAMを割り当て続けます。
    割り当て量が目標値を下回れば追加確保、上回れば解放します。
    """
    device = torch.device(f'cuda:{gpu_id}')
    print(f"[INFO] Starting VRAM load on GPU {gpu_id} => target={vram_percentage}% of total memory.")

    allocated_tensors = []

    while not stop_event.is_set():
        free_mem, total_mem = torch.cuda.mem_get_info(device=device)
        used_mem = total_mem - free_mem
        target_bytes = int(total_mem * (vram_percentage / 100.0))
        current_alloc = used_mem

        if current_alloc < target_bytes:
            to_allocate = target_bytes - current_alloc
            chunk_size = to_allocate // 10
            if chunk_size < 1:
                chunk_size = 1
            # float32: 4バイト
            chunk_size_float = chunk_size // 4
            if chunk_size_float > 0:
                try:
                    tensor = torch.zeros(chunk_size_float, dtype=torch.float32, device=device)
                    allocated_tensors.append(tensor)
                except RuntimeError as e:
                    print(f"[WARN] OOM on GPU {gpu_id}: {e}")
                    time.sleep(1.0)
            time.sleep(0.1)
        elif current_alloc > target_bytes:
            to_free = current_alloc - target_bytes
            freed = 0
            while freed < to_free and allocated_tensors:
                pop_t = allocated_tensors.pop()
                freed += pop_t.numel() * 4
                del pop_t
            torch.cuda.empty_cache()
            time.sleep(0.1)
        else:
            time.sleep(0.2)

    print(f"[INFO] Stopping VRAM load on GPU {gpu_id}. Freed all allocated tensors.")
    del allocated_tensors
    torch.cuda.empty_cache()
    print(f"[INFO] GPU {gpu_id} memory freed.")

# CUDA環境向けVRAM負荷は、各GPUに対して個別のスレッドを起動する関数にする
def apply_gpu_vram_load(load_percentage, stop_event, gpu_ids):
    print(f"Starting GPU VRAM Load with {load_percentage}% on GPUs: {gpu_ids}")
    for gpu_id in gpu_ids:
        threading.Thread(
            target=allocate_vram_dynamic,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()

######################################
# 上位スクリプト用のエイリアス定義
######################################
apply_gpu_tensor_load_func = apply_gpu_tensor_load
apply_combined_load_func = apply_combined_load
apply_gpu_vram_load_func = apply_gpu_vram_load

# ※ 上位スクリプト側は、これらの名前で関数を参照する前提です。

