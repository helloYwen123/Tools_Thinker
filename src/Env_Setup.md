
# 环境配置与安装指南

本指南介绍了如何设置 Conda 环境并安装所需的依赖包，以运行本项目。



## 1. 环境创建与激活

首先，创建一个新的 Conda 环境。我们推荐使用 Python 3.11。

```bash
conda create -n v_thinker python=3.11 pip -y
```

创建成功后，激活该环境：

```bash
conda activate v_thinker
```

**注意：** 后续所有安装命令都应在此激活的环境中执行。

## 3. 安装 PyTorch

根据 CUDA 版本（或选择 CPU 版本），安装 PyTorch、TorchVision 和 TorchAudio。（ [PyTorch 官网](https://pytorch.org/get-started/locally/) ）：

```bash
# 命令
pip3 install torch torchvision torchaudio
```


## 4. 安装依赖项

项目所需的其他依赖项列在 `requirements.txt` 文件中。

首先，确保终端位于`requirements.txt` 文件所在目录

```bash
cd ~/syang_docker/Tools_Thinker/src 
```

然后，使用 pip 安装这些依赖：

```bash
pip install -r requirements.txt
```

## 5. 安装本地包

本项目包含一些本地开发的包，需要单独安装。

### 5.1 安装 `toolsbase` 包

导航到项目根目录 `Tools_Thinker/`（如果尚未在此目录）：

```bash
cd ~/syang_docker/Tools_Thinker 
```

执行以下命令以 editable 模式安装 `toolsbase`：

```bash
pip install -e .
```

*(`-e` 标志表示 "editable"，这意味着对源代码的更改将直接反映在已安装的包中，无需重新安装，非常适合开发。)*

### 5.2 安装 `r1-v` 包

导航到 `open_r1_multimodal` 目录：

```bash
cd ~/syang_docker/Tools_Thinker/src/open_r1_multimodal
```

执行以下命令以 editable 模式安装 `r1-v`：

```bash
pip install -e .
```

安装完成后，你的环境应该已经配置完毕，可以开始运行项目代码了。


