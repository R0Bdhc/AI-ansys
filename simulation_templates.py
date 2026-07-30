"""
simulation_templates.py
预定义结构仿真模板，覆盖：几何创建、材料定义、网格控制、加载与求解。
支持参数化覆盖，输出标准化 APDL 命令列表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


# ───────────────────────────────
# 1. 悬臂梁弯曲模板
# ───────────────────────────────

@dataclass
class CantileverBeamParams:
    length: float = 1.0          # 梁长度 (m)
    width: float = 0.1           # 截面宽度 (m)
    height: float = 0.1          # 截面高度 (m)
    mesh_size: float = 0.02      # 全局网格尺寸 (m)
    young_modulus: float = 2.0e11  # 弹性模量 (Pa)
    poisson_ratio: float = 0.3   # 泊松比
    force_y: float = -1000.0     # 端部 Y 向力 (N)
    element_type: str = "SOLID185"  # 体单元类型


class CantileverBeamTemplate:
    """标准悬臂梁弯曲仿真。

    几何：长方体，一端固定，另一端受 Y 向集中力。
    网格：映射六面体（sweep/map）或自由划分。
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        raw = params or {}
        self.p = CantileverBeamParams(**{k: v for k, v in raw.items() if k in CantileverBeamParams.__dataclass_fields__})

    def build_apdl(self) -> list[str]:
        p = self.p
        cmds = [
            "/CLEAR,START",
            "/PREP7",
            f"ET,1,{p.element_type}",
            f"MP,EX,1,{p.young_modulus:.6e}",
            f"MP,PRXY,1,{p.poisson_ratio:.6f}",
            # 创建长方体
            f"BLOCK,0,{p.length},0,{p.width},0,{p.height}",
            # 网格控制
            f"ESIZE,{p.mesh_size}",
            "MSHAPE,0,3D",        # 六面体
            "MSHKEY,1",           # 映射网格
            "VMESH,ALL",
            # 固定端约束（X=0 面）
            "NSEL,S,LOC,X,0",
            "D,ALL,ALL,0",
            "NSEL,ALL",
            # 加载端节点选择（X=length 面，选择中心节点施加集中力）
            f"NSEL,S,LOC,X,{p.length}",
            "NSEL,R,LOC,Y,0",
            "NSEL,R,LOC,Z,0",
            "*GET,LOAD_NODE,NODE,,NUM,MIN",
            "NSEL,ALL",
            "F,LOAD_NODE,FY,{:.6e}".format(p.force_y),
            # 求解
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            "ALLSEL",
            "*GET,TIP_UY,NODE,LOAD_NODE,U,Y",
        ]
        return cmds

    def get_info(self) -> dict[str, Any]:
        return {
            "template_name": "cantilever_beam",
            "description": "标准悬臂梁弯曲仿真，映射六面体网格，端部集中力加载。",
            "analysis_type": "static_structural",
            "default_params": self.p.__dict__,
        }


# ───────────────────────────────
# 2. 带孔平板应力集中模板
# ───────────────────────────────

@dataclass
class PlateWithHoleParams:
    plate_length: float = 2.0    # 板长度 (m)
    plate_width: float = 1.0     # 板宽度 (m)
    plate_thickness: float = 0.05  # 板厚度 (m)
    hole_radius: float = 0.1     # 孔半径 (m)
    mesh_size: float = 0.03      # 全局网格尺寸
    mesh_size_hole: float = 0.01  # 孔边局部加密尺寸
    young_modulus: float = 2.0e11
    poisson_ratio: float = 0.3
    traction_x: float = 1.0e7    # X 向拉应力 (Pa)
    element_type: str = "SOLID185"


class PlateWithHoleTemplate:
    """带圆孔平板应力集中仿真。

    几何：长方体减去圆柱（圆孔）。
    网格：自由四面体，孔边局部加密。
    加载：一端 clamp (UX=UY=UZ=0)，对边施加均匀拉应力。
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        raw = params or {}
        self.p = PlateWithHoleParams(**{k: v for k, v in raw.items() if k in PlateWithHoleParams.__dataclass_fields__})

    def build_apdl(self) -> list[str]:
        p = self.p
        half_l = p.plate_length / 2.0
        half_w = p.plate_width / 2.0
        cmds = [
            "/CLEAR,START",
            "/PREP7",
            f"ET,1,{p.element_type}",
            f"MP,EX,1,{p.young_modulus:.6e}",
            f"MP,PRXY,1,{p.poisson_ratio:.6f}",
            # 创建平板并挖孔（以原点为中心）
            f"BLOCK,-{half_l},{half_l},-{half_w},{half_w},0,{p.plate_thickness}",
            f"CYL4,0,0,0,{p.hole_radius},,,{p.plate_thickness}",
            "VSBV,1,2",           # 体减运算，生成带孔板
            # 网格控制：孔边加密
            f"LESIZE,ALL,{p.mesh_size}",
            "LSEL,S,LENGTH,,0.1",  # 选择孔边短边（近似）
            f"LESIZE,ALL,{p.mesh_size_hole}",
            "LSEL,ALL",
            "MSHAPE,1,3D",        # 四面体
            "MSHKEY,0",           # 自由网格
            "VMESH,ALL",
            # 一端固定（X = -half_l）
            f"NSEL,S,LOC,X,-{half_l}",
            "D,ALL,ALL,0",
            "NSEL,ALL",
            # 对边施加均匀拉应力（X = +half_l）
            f"NSEL,S,LOC,X,{half_l}",
            "SF,ALL,PRES,-{:.6e}".format(p.traction_x),
            "NSEL,ALL",
            # 求解
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            "ALLSEL",
        ]
        return cmds

    def get_info(self) -> dict[str, Any]:
        return {
            "template_name": "plate_with_hole",
            "description": "带圆孔平板应力集中仿真，自由四面体网格，孔边局部加密，一端固定对边拉伸。",
            "analysis_type": "static_structural",
            "default_params": self.p.__dict__,
        }


# ───────────────────────────────
# 3. 粘弹性圆盘压缩模板
# ───────────────────────────────

@dataclass
class ViscoelasticDiskParams:
    disk_radius: float = 0.05      # 圆盘半径 (m)
    disk_height: float = 0.02      # 圆盘高度 (m)
    mesh_size: float = 0.003
    young_modulus: float = 2.0e6   # 弹性模量 (Pa) — 橡胶量级
    poisson_ratio: float = 0.49    # 近似不可压缩
    # Prony 剪切松弛参数
    prony_g1: float = 0.5          # 相对模量
    prony_tau1: float = 1.0        # 松弛时间 (s)
    # 加载
    compress_displacement: float = -0.005  # Z 向压缩位移 (m)
    final_time: float = 10.0       # 终止时间 (s)
    num_substeps: int = 50
    element_type: str = "SOLID185"


class ViscoelasticDiskTemplate:
    """粘弹性聚合物圆盘压缩仿真。

    几何：圆柱体。
    材料：线弹性基体 + Prony 剪切松弛（粘弹性）。
    加载：底面固定，顶面施加 Z 向位移压缩。
    求解：瞬态分析，静态时间步进。
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        raw = params or {}
        self.p = ViscoelasticDiskParams(**{k: v for k, v in raw.items() if k in ViscoelasticDiskParams.__dataclass_fields__})

    def build_apdl(self) -> list[str]:
        p = self.p
        cmds = [
            "/CLEAR,START",
            "/PREP7",
            f"ET,1,{p.element_type}",
            # 材料：线弹性基体
            f"MP,EX,1,{p.young_modulus:.6e}",
            f"MP,PRXY,1,{p.poisson_ratio:.6f}",
            # Prony 剪切松弛（TB,PRONY）
            "TB,PRONY,1,,1,SHEAR",
            f"TBTEMP,0",
            f"TBPT,,{p.prony_g1:.6f},{p.prony_tau1:.6f}",
            # 创建圆柱
            f"CYL4,0,0,0,{p.disk_radius},,,{p.disk_height}",
            # 网格控制
            f"ESIZE,{p.mesh_size}",
            "MSHAPE,0,3D",
            "MSHKEY,1",
            "VMESH,ALL",
            # 底面固定（Z=0）
            "NSEL,S,LOC,Z,0",
            "D,ALL,ALL,0",
            "NSEL,ALL",
            # 顶面压缩位移（Z=disk_height）
            f"NSEL,S,LOC,Z,{p.disk_height}",
            "D,ALL,UZ,{:.6e}".format(p.compress_displacement),
            "D,ALL,UX,0",
            "D,ALL,UY,0",
            "NSEL,ALL",
            # 瞬态求解
            "/SOLU",
            "ANTYPE,TRANS",
            "TRNOPT,FULL",
            "TIME,{:.6f}".format(p.final_time),
            "NSUBST,{},1,{}".format(p.num_substeps, p.num_substeps * 2),
            "AUTOTS,ON",
            "OUTRES,ALL,ALL",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            "ALLSEL",
        ]
        return cmds

    def get_info(self) -> dict[str, Any]:
        return {
            "template_name": "viscoelastic_disk",
            "description": "粘弹性聚合物圆盘压缩仿真，Prony 剪切松弛，映射六面体网格，顶面位移加载。",
            "analysis_type": "transient_structural",
            "default_params": self.p.__dict__,
        }


# ───────────────────────────────
# 模板工厂
# ───────────────────────────────

TEMPLATE_REGISTRY: dict[str, type] = {
    "cantilever": CantileverBeamTemplate,
    "plate_with_hole": PlateWithHoleTemplate,
    "viscoelastic_disk": ViscoelasticDiskTemplate,
}


def list_templates() -> list[dict[str, Any]]:
    """返回所有可用模板的元信息列表。"""
    return [cls().get_info() for cls in TEMPLATE_REGISTRY.values()]


def build_template(template_type: str, params: dict[str, Any] | None = None) -> list[str]:
    """根据模板类型和参数生成 APDL 命令列表。"""
    if template_type not in TEMPLATE_REGISTRY:
        raise ValueError(f"未知模板类型：{template_type}。可用：{list(TEMPLATE_REGISTRY.keys())}")
    return TEMPLATE_REGISTRY[template_type](params).build_apdl()


def get_template_info(template_type: str) -> dict[str, Any]:
    """获取指定模板的元信息。"""
    if template_type not in TEMPLATE_REGISTRY:
        raise ValueError(f"未知模板类型：{template_type}。可用：{list(TEMPLATE_REGISTRY.keys())}")
    return TEMPLATE_REGISTRY[template_type]().get_info()
