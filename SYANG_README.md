Hey, Wenjie你好呀:

在训练开始前，请先确保在marajo一侧启动服务，这部分由我来做
1. cd到docker_apis文件夹下方
    * 若未build, 可以先运行docker compose build
2. docker compose up -d

训练模型通过在madeira节点运行以下命令：
1. cd到bash文件所在目录
2. sbatch syang_train_model.sh，你可能需要根据你的情况对里面的内容做适当修改，比如初始化conda环境等地方

Yang Shucheng版本主要修改如下几个文件：
1. Tools_Thinker/src/open_r1_multimodal/configs/prompt_configuration_file_syang.yaml
    改动内容：
        由部分工具可用改为所有工具可用

2. Tools_Thinker/src/open_r1_multimodal/run_grpo_thinker_syang.sh
    改动内容：
        将代码的运行和工具的调用解耦到marajo一侧
        madeira上的thinker在训练时只负责生成代码，发送给marajo处理，并得到结果，更新模型

3. Tools_Thinker/src/open_r1_multimodal/configs/zero3_syang.yaml
    改动内容：
        offload_optimizer_device: cpu
        offload_param_device: cpu
        将以上两个参数值由none改为cpu，缓解内存不够用问题（OOM）

4. Tools_Thinker/src/open_r1_multimodal/run_grpo_thinker_syang.sh
    改动内容：
        训练模型的主代码文件名更新
        --confige_file和--confile后对应配置文件的文件名更新
        --report_to wandb改为none,我没有详细配置wandb各种参数，所以改为none，如果你那边已经配好了，可以改回来

        以下是缓解OOM问题：
        --gradient_accumulation_steps由2降为1
        --attn_implementation 由flash_attn_2改为eager，以支持更多GPU上训练，如果有足够的A6000, H100等显卡，可将其改为flash_attn_2
        --num_generations 8改为2

备注：
Tools_Thinker/src/tools里面的工具代码我未做任何改动，我的工具调用主要逻辑已经解耦到marajo端侧的docker_apis文件夹中，所有工具调用和代码实现都在那里进行；不过如果需要对工具进行修改或者扩充，你仍然可以基于这个Tools_Thinker/src/tools开发，我会pull你的代码到我的分支，然后移植到我的docker_apis工具调用代码中。

备注2：
如果有任何其他问题可以随时邮件shucheng.yang@tum.de
或者微信ysc0034
        