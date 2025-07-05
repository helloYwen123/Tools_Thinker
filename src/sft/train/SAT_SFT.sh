export WANDB_PROJECT="sft"
export WANDB_API_KEY="2d883ab1037c7c4b261d54b523c3515fa87dde91"

oumi train -c traintools.yaml \
  --training.learning_rate 2e-5 \
