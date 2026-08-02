# GeoGebra → Asymptote 完整使用手册

## 目录

1. [工具简介](#1-工具简介)
2. [安装](#2-安装)
3. [基本使用](#3-基本使用)
4. [命令行参数](#4-命令行参数)
5. [输出代码结构](#5-输出代码结构)
6. [支持的对象](#6-支持的对象)
7. [自动样式规则](#7-自动样式规则)
8. [画布与比例](#8-画布与比例)
9. [编译 Asymptote](#9-编译-asy)
10. [Python API](#10-python-api)
11. [批量转换](#11-批量转换)
12. [常见问题](#12-常见问题)
13. [已知限制](#13-已知限制)
14. [项目结构](#14-项目结构)
15. [开发与测试](#15-开发与测试)
## 1. 工具简介

本工具用于把 GeoGebra `.ggb` 文件转换为可读、可编辑的 Asymptote `.asy` 源代码。

`.ggb` 文件本质上是一个压缩包，内部包含描述几何对象和依赖关系的 XML。转换器会读取其中的 `geogebra.xml`，解析对象坐标、构造命令、显示状态、线型、颜色和标签信息，再生成与原图对应的 Asymptote 代码。

适合以下用途：

- 将 GeoGebra 作图用于 LaTeX 试卷、讲义、论文或竞赛题解
- 获取比截图更清晰的矢量图
- 将 GeoGebra 图形转换成可手工修改的 Asymptote 源码
- 批量处理已有 `.ggb` 文件
- 在 Python 程序中继续处理生成结果

## 2. 安装

### 2.1 检查 Python

```powershell
py --version
```

需要 Python 3.10 或更高版本。

### 2.2 创建虚拟环境

进入项目目录：

```powershell
cd "C:\Users\你的用户名\Documents\grapher"
py -m venv .venv
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果出现“禁止运行脚本”错误：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

### 2.3 安装命令

```powershell
python -m pip install -e .
```

`-e` 表示可编辑安装。修改项目源码后，不需要反复重新安装。

验证安装：

```powershell
ggb2asy --help
```

## 3. 基本使用

### 3.1 指定输出文件

```powershell
ggb2asy "input.ggb" -o "output.asy"
```

路径中含有空格、中文或特殊字符时，应使用双引号。

### 3.2 自动确定输出文件名

```powershell
ggb2asy "example.ggb"
```

程序会在同一目录生成 `example.asy`。

### 3.3 使用完整路径

```powershell
ggb2asy `
  "C:\Users\你的用户名\Desktop\几何图.ggb" `
  -o "C:\Users\你的用户名\Desktop\几何图.asy"
```

PowerShell 中的反引号表示命令在下一行继续。

### 3.4 不使用命令入口

如果 `ggb2asy` 暂时无法识别：

```powershell
python -m grapher.cli "input.ggb" -o "output.asy"
```

## 4. 命令行参数

完整格式：

```text
ggb2asy INPUT [-o OUTPUT] [--preserve-style] [--debug]
```

### `INPUT`

必须提供，表示输入 `.ggb` 文件。

### `-o`, `--output`

指定输出 `.asy` 文件：

```powershell
ggb2asy "triangle.ggb" --output "triangle.asy"
```

### `--preserve-style`

精确保留 GeoGebra 中记录的颜色和线宽：

```powershell
ggb2asy "triangle.ggb" -o "triangle.asy" --preserve-style
```

默认模式与该选项的区别：

| 项目 | 默认模式 | `--preserve-style` |
| --- | --- | --- |
| 灰色主体线 | 转换为黑色 | 保留原灰色 |
| 彩色对象 | 保留明显颜色 | 精确保留颜色 |
| 虚线、点线 | 保留 | 保留 |
| 线宽 | 使用适合排版的统一细线 | 按 GeoGebra 线宽换算 |
| 点颜色 | 保留明显颜色，灰色点使用黑色 | 精确保留颜色和大小 |

一般数学文档建议使用默认模式。需要尽量复刻 GeoGebra 外观时使用 `--preserve-style`。

### `--debug`

在生成的 `.asy` 中加入调试注释：

```powershell
ggb2asy "triangle.ggb" -o "triangle.asy" --debug
```

调试信息包括：

- 读取的 XML 文件名
- 解析到的对象数量
- 不支持或无法完整转换的对象
- 缺少端点、矩阵或表达式时的警告

## 5. 输出代码结构

生成文件通常包含以下部分：

```asy
usepackage("amsmath");
size(8cm, keepAspect=true);
import graph;
import geometry;
import olympiad;

pen thinline = linewidth(0.5);
pen axispen = linewidth(0.2);
pen dotpen = linewidth(1) + black;
defaultpen(fontsize(8));

pair A = (0, 3);
pair B = (-2, 0);
pair C = (2, 0);

draw(A--B, thinline);
draw(B--C, thinline);
draw(C--A, thinline);

label("$A$", A, N);
label("$B$", B, SW);
label("$C$", C, SE);
```

输出顺序大致为：

1. Asymptote 包和全局样式
2. 点坐标定义
3. 函数或参数辅助定义
4. 曲线与直线
5. 坐标轴和网格
6. 角标记
7. 点和标签
8. 画布裁剪

## 6. 支持的对象

### 6.1 点

- 读取齐次坐标并转换为普通二维坐标
- 保留点名和标签显示状态
- 自动处理 `E`、`N`、`S`、`O` 等 Asymptote 保留名称
- 将 `A'` 等名称转换为合法变量名，同时保留原标签文本

例如：

```asy
pair Ap = (1, 2);
label("$A'$", Ap, NW);
```

### 6.2 点标记

普通独立点会生成 `dot()`。当某点位于至少两条不同的可见直线上时，交点本身通常已经足够清楚，因此不会额外生成实心点。

### 6.3 线类对象

- 线段：`draw(A--B, pen)`
- 直线：按照 GeoGebra 视口裁剪
- 射线：从起点向指定方向延伸并裁剪
- 向量：使用箭头绘制
- 多边形和折线：按照顶点顺序连接

### 6.4 圆和圆锥曲线

- 圆优先转换为 Asymptote `circle`
- 圆弧、扇形和半圆按照定义点转换
- 椭圆、双曲线及一般二次曲线根据 GeoGebra 矩阵生成隐式方程
- 一般二次曲线使用 Asymptote `contour` 绘制

当输出中使用 `contour` 时，会自动加入：

```asy
import contour;
```

### 6.5 函数

常见显式函数会转换为 Asymptote 函数和 `graph()` 绘图命令。

### 6.6 角标记

可见角对象会生成半径随画布缩放的小圆弧 `arc()`。当前版本按几何图常用习惯绘制锐角标记，并自动调整射线方向，避免错误地标记成外角、钝角或过大的角弧。

### 6.7 坐标轴和网格

如果 GeoGebra 视图启用了坐标轴或网格，输出会生成对应 Asymptote 图形。网格范围过大时会跳过，以避免生成数百条无意义代码。

## 7. 自动样式规则

### 7.1 颜色

默认模式会判断颜色是否为“中性灰色”：

- 黑色、灰色、接近灰色的主体线统一输出为黑色
- 青色、蓝色、红色等明显彩色对象保留颜色
- 彩色点也会保留颜色

这样既能保留原图中真正有意义的颜色，又不会把 GeoGebra 界面的默认灰色带入数学排版。

### 7.2 线型

GeoGebra 线型会映射为 Asymptote 画笔：

| GeoGebra 线型 | Asymptote |
| --- | --- |
| 实线 | 普通画笔 |
| 长虚线 | `dashed` |
| 短虚线 | `dashed` |
| 点线 | `dotted` |
| 点划线 | `dashdotted` |

### 7.3 标签

自动标签布局会综合考虑：

- 标签文字的估算宽高和实际占用边界框
- 附近其他标签的边界框和安全间距
- 点经过的直线和线段方向
- 圆在该点处的径向方向
- 一般圆锥曲线在该点处的切线
- 标签与直线、曲线和其他点的距离
- GeoGebra 中已有的手工标签偏移

布局会同时尝试 8 个方向以及普通、`1.25` 倍和 `1.5` 倍三档距离，对标签框重叠、线与曲线穿过标签、邻近点、画布溢出等情况进行评分。程序优先选择没有碰撞且离原点较近的位置，只有空间拥挤时才增大偏移。

自动布局不能保证所有极端密集图形完全无需修改。生成后可以直接编辑：

```asy
label("$A$", A, N);
label("$B$", B, 1.25*SW);
label("$C$", C, 1.5*E);
```

常用方向：

```text
N  NE  E  SE  S  SW  W  NW
```

## 8. 画布与比例

转换器不会直接使用整个 GeoGebra 窗口作为输出范围，而是根据可见点和圆计算紧凑边界：

- 自动加入少量留白
- 避免画布过宽或过高
- 保持几何对象比例
- 使用不可见矩形确定最终尺寸
- 最后裁剪超出画布的直线和曲线

生成代码中可以看到：

```asy
draw(box((-3, -2), (5, 4)), invisible);
clip(box((-3, -2), (5, 4)));
```

如需改变最终图片大小，可修改：

```asy
size(8cm, keepAspect=true);
```

## 9. 编译 `.asy`

生成 PDF：

```powershell
asy -f pdf "output.asy"
```

生成 PNG：

```powershell
asy -f png "output.asy"
```

生成 EPS：

```powershell
asy -f eps "output.asy"
```

在 LaTeX 中可直接插入生成的 PDF：

```latex
\usepackage{graphicx}

\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.6\textwidth]{output.pdf}
\end{figure}
```

## 10. Python API

公开接口：

```python
from grapher import convert_ggb_to_asy
```

函数签名：

```python
convert_ggb_to_asy(
    input_path,
    output_path=None,
    *,
    preserve_style=False,
    debug=False,
)
```

参数说明：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `input_path` | `str` 或 `Path` | 输入 `.ggb` 文件 |
| `output_path` | `str`、`Path` 或 `None` | 输出 `.asy` 文件；为 `None` 时不写文件 |
| `preserve_style` | `bool` | 是否精确保留 GeoGebra 样式 |
| `debug` | `bool` | 是否生成调试注释 |

返回值包含：

| 属性 | 说明 |
| --- | --- |
| `result.code` | 生成的完整 Asymptote 源码 |
| `result.objects` | 解析出的 GeoGebra 对象 |
| `result.warnings` | 转换警告列表 |

示例：

```python
from pathlib import Path
from grapher import convert_ggb_to_asy

source = Path("input.ggb")
target = source.with_suffix(".asy")
result = convert_ggb_to_asy(source, target)

for warning in result.warnings:
    print("warning:", warning)
```

只获取代码：

```python
result = convert_ggb_to_asy("input.ggb")
asy_code = result.code
```

## 11. 批量转换

```python
from pathlib import Path
from grapher import convert_ggb_to_asy

source_dir = Path("ggb-files")
output_dir = Path("asy-files")
output_dir.mkdir(exist_ok=True)

for ggb_path in source_dir.glob("*.ggb"):
    output_path = output_dir / ggb_path.with_suffix(".asy").name
    result = convert_ggb_to_asy(ggb_path, output_path)
    print(f"{ggb_path.name} -> {output_path.name}")
    for warning in result.warnings:
        print("  warning:", warning)
```

## 12. 常见问题

### 12.1 无法识别 `ggb2asy`

错误示例：

```text
ggb2asy : 无法将“ggb2asy”项识别为 cmdlet、函数、脚本文件或可运行程序
```

处理步骤：

```powershell
cd "C:\Users\你的用户名\Documents\grapher"
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
ggb2asy --help
```

也可以直接运行：

```powershell
python -m grapher.cli "input.ggb" -o "output.asy"
```

### 12.2 修改代码后效果没有变化

可能正在运行旧安装版本。重新执行：

```powershell
python -m pip install -e .
```

检查命令位置：

```powershell
Get-Command ggb2asy
```

### 12.3 路径中有空格或中文

使用双引号包围完整路径：

```powershell
ggb2asy "C:\Users\Name\My Files\几何图.ggb"
```

### 12.4 生成图中缺少对象

使用调试模式：

```powershell
ggb2asy "input.ggb" -o "output.asy" --debug
```

检查终端警告以及 `.asy` 文件末尾的注释。对象也可能在 GeoGebra 中被设置为不可见。

### 12.5 Asymptote 无法识别

确认 Asymptote 已安装并加入 `PATH`：

```powershell
asy --version
```

使用 TeX Live 时，`asy.exe` 通常位于类似目录：

```text
C:\texlive\2025\bin\windows
```

### 12.6 标签仍有少量重叠

直接修改生成代码中的方向或倍数：

```asy
label("$P$", P, NE);
label("$Q$", Q, 1.25*W);
```

对于极其拥挤的竞赛几何图，少量手工微调通常比无限增加自动布局复杂度更可靠。

### 12.7 输出画布仍不合适

可以手工修改不可见边界和裁剪范围：

```asy
draw(box((-5, -3), (6, 5)), invisible);
clip(box((-5, -3), (6, 5)));
```

## 13. 已知限制

- 不保留 GeoGebra 的动态拖动和交互行为
- 复杂文本、公式文本框、图片和按钮尚未完整支持
- 填充颜色、透明度和阴影可能无法精确复刻
- 部分高级轨迹、样条曲线和三维对象可能被跳过
- 参数依赖会转化为当前静态坐标，不会完整重建 GeoGebra 代数系统
- 一般隐式曲线的绘制范围取决于 GeoGebra 视口
- 非常密集的标签仍可能需要手工调整

## 14. 项目结构

```text
grapher/
├─ pyproject.toml
├─ README.md
├─ docs/
│  └─ USAGE.zh-CN.md
├─ src/
│  └─ grapher/
│     ├─ __init__.py
│     ├─ cli.py
│     ├─ converter.py
│     ├─ models.py
│     └─ parser.py
└─ tests/
   └─ test_converter.py
```

模块职责：

- `parser.py`：读取 `.ggb`、解析 XML、合并命令和对象
- `converter.py`：几何映射、样式处理、标签布局和 Asymptote 生成
- `models.py`：对象、视口和转换结果数据结构
- `cli.py`：命令行参数和文件输出
- `__init__.py`：公开 Python API

## 15. 开发与测试

安装开发版本：

```powershell
python -m pip install -e .
```

运行全部测试：

```powershell
python -m unittest discover -s tests -v
```

当前标签布局还使用 76 个真实 GeoGebra 文件（70 个去重图形）进行批量回归：全部文件均可转换，70/70 个唯一图形均可由 Asymptote 编译；在 625 个可见标签的估算边界框中，仅有两对位于同一张极端密集图中的标签发生重叠。

检查 Python 文件语法：

```powershell
python -m py_compile `
  src\grapher\parser.py `
  src\grapher\converter.py `
  src\grapher\cli.py
```

验证真实文件时，建议按以下顺序：

1. 使用 `ggb2asy` 生成 `.asy`
2. 检查终端警告
3. 使用 `asy -f pdf` 编译
4. 对照 GeoGebra 原图检查坐标、虚实线、颜色和标签
5. 必要时手工微调少量标签


