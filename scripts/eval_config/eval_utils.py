# qwen2vl_utils.py

import torch
from typing import Optional, Dict, List, Union, Literal

def get_rope_index(
    processor,
    input_ids: torch.Tensor,
    image_grid_thw: Optional[torch.Tensor] = None,
    video_grid_thw: Optional[torch.Tensor] = None,
    second_per_grid_ts: Optional[torch.Tensor] = None,
    attention_mask: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """
    Compute 3D RoPE-based position_ids for Qwen2-VL.
    Used for multimodal sequences containing vision tokens.
    """
    spatial_merge_size = processor.image_processor.merge_size
    tokens_per_second = 2
    image_token_id = processor.tokenizer.convert_tokens_to_ids("<|image_pad|>")
    video_token_id = processor.tokenizer.convert_tokens_to_ids("<|video_pad|>")
    vision_start_token_id = processor.tokenizer.convert_tokens_to_ids("<|vision_start|>")

    if input_ids is not None and (image_grid_thw is not None or video_grid_thw is not None):
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids)

        position_ids = torch.ones(3, input_ids.size(0), dtype=input_ids.dtype, device=input_ids.device)
        image_index, video_index = 0, 0
        input_ids = input_ids[attention_mask == 1]

        vision_start_indices = torch.argwhere(input_ids == vision_start_token_id)
        vision_tokens = input_ids[vision_start_indices + 1]
        image_nums = (vision_tokens == image_token_id).sum()
        video_nums = (vision_tokens == video_token_id).sum()

        input_tokens = input_ids.tolist()
        llm_pos_ids_list = []
        st = 0
        remain_images, remain_videos = image_nums, video_nums

        for _ in range(image_nums + video_nums):
            if image_token_id in input_tokens and remain_images > 0:
                ed_image = input_tokens.index(image_token_id, st)
            else:
                ed_image = len(input_tokens) + 1
            if video_token_id in input_tokens and remain_videos > 0:
                ed_video = input_tokens.index(video_token_id, st)
            else:
                ed_video = len(input_tokens) + 1

            if ed_image < ed_video:
                t, h, w = image_grid_thw[image_index]
                second_per_grid_t = 0
                image_index += 1
                remain_images -= 1
                ed = ed_image
            else:
                t, h, w = video_grid_thw[video_index]
                second_per_grid_t = second_per_grid_ts[video_index] if second_per_grid_ts is not None else 1.0
                video_index += 1
                remain_videos -= 1
                ed = ed_video

            llm_grid_t, llm_grid_h, llm_grid_w = t.item(), h.item() // spatial_merge_size, w.item() // spatial_merge_size
            text_len = ed - st
            st_idx = llm_pos_ids_list[-1].max() + 1 if len(llm_pos_ids_list) > 0 else 0
            llm_pos_ids_list.append(torch.arange(text_len).view(1, -1).expand(3, -1) + st_idx)

            t_index = torch.arange(llm_grid_t).view(-1, 1).expand(-1, llm_grid_h * llm_grid_w)
            t_index = (t_index * second_per_grid_t * tokens_per_second).long().flatten()
            h_index = torch.arange(llm_grid_h).view(1, -1, 1).expand(llm_grid_t, -1, llm_grid_w).flatten()
            w_index = torch.arange(llm_grid_w).view(1, 1, -1).expand(llm_grid_t, llm_grid_h, -1).flatten()
            llm_pos_ids_list.append(torch.stack([t_index, h_index, w_index]) + text_len + st_idx)
            st = ed + llm_grid_t * llm_grid_h * llm_grid_w

        if st < len(input_tokens):
            st_idx = llm_pos_ids_list[-1].max() + 1 if len(llm_pos_ids_list) > 0 else 0
            text_len = len(input_tokens) - st
            llm_pos_ids_list.append(torch.arange(text_len).view(1, -1).expand(3, -1) + st_idx)

        llm_positions = torch.cat(llm_pos_ids_list, dim=1).reshape(3, -1)
        position_ids[..., attention_mask == 1] = llm_positions.to(position_ids.device)
    else:
        if attention_mask is not None:
            position_ids = attention_mask.long().cumsum(-1) - 1
            position_ids.masked_fill_(attention_mask == 0, 1)
            position_ids = position_ids.unsqueeze(0).expand(3, -1).to(input_ids.device)
        else:
            position_ids = torch.arange(input_ids.shape[1], device=input_ids.device).view(1, -1).expand(3, -1)

    return position_ids


def postprocess_data(
    input_ids: torch.Tensor,
    attention_mask: torch.Tensor,
    position_ids: torch.Tensor,
    max_length: int,
    pad_token_id: int,
    left_pad: bool = True,
    truncation: Literal["left", "right", "error"] = "error",
):
    """Pad or truncate data."""
    assert truncation in ["left", "right", "error"]
    seq_length = len(input_ids)
    if seq_length < max_length:
        input_ids = pad_sequence_to_length(
            input_ids, max_seq_len=max_length, pad_token_id=pad_token_id, left_pad=left_pad
        )
        attention_mask = pad_sequence_to_length(
            attention_mask, max_seq_len=max_length, pad_token_id=0, left_pad=left_pad
        )
        position_ids = pad_sequence_to_length(position_ids, max_seq_len=max_length, pad_token_id=0, left_pad=left_pad)
    elif seq_length > max_length:
        if truncation == "left":  # actually, left truncation may not be reasonable
            input_ids = input_ids[..., -max_length:]
            attention_mask = attention_mask[..., -max_length:]
            position_ids = position_ids[..., -max_length:]
        elif truncation == "right":
            input_ids = input_ids[..., :max_length]
            attention_mask = attention_mask[..., :max_length]
            position_ids = position_ids[..., :max_length]
        elif truncation == "error":
            raise RuntimeError(f"Input sequence length {seq_length} is longer than max length {max_length}.")
        else:
            raise NotImplementedError(f"Unknown truncation method {truncation}.")

    return input_ids, attention_mask, position_ids

def pad_sequence_to_length(tensor: torch.Tensor, max_seq_len: int, pad_token_id: int, left_pad: bool = False):
    """Pad a tensor in its last dimension to `max_seq_len`."""
    if tensor.size(-1) >= max_seq_len:
        return tensor
    pad_shape = list(tensor.shape)
    pad_shape[-1] = max_seq_len - tensor.size(-1)
    pad_tensor = torch.full(pad_shape, fill_value=pad_token_id, dtype=tensor.dtype, device=tensor.device)
    return torch.cat((pad_tensor, tensor), dim=-1) if left_pad else torch.cat((tensor, pad_tensor), dim=-1)




def get_response_mask(
    response_ids: torch.Tensor, eos_token_id: Union[int, List[int]] = 2, dtype: torch.dtype = torch.long
):
    """Get the mask for the response ids, the mask will be 0 after the first eos token.

    eos_token_id can be int or list: 1 or [1, 2].
    ```
    e.g. eos_token = 1
    response_ids:  [0, 0, 2, 4, 3, 5, 1, 0, 0]
    response_mask: [1, 1, 1, 1, 1, 1, 1, 0, 0]
    ```
    """
    if isinstance(eos_token_id, int):
        eos_token_id = [eos_token_id]

    response_mask = torch.zeros_like(response_ids, dtype=torch.bool)
    for token_id in eos_token_id:
        response_mask |= response_ids.eq(token_id)

    response_mask = response_mask.long()
    response_mask = (torch.cumsum(response_mask, dim=1) - response_mask).bool()
    response_mask = torch.logical_not(response_mask).to(dtype)
    return response_mask


def pad_2d_list_to_length(
    response: List[List[int]], pad_token_id: int, max_length: Optional[int] = None
) -> torch.Tensor:
    """Pad a 2D list (e.g. responses, log_probs) to a 2D tensor."""
    max_response_length = max(len(sub_list) for sub_list in response)
    if max_length is not None and max_length > max_response_length:
        target_length = max_length
    else:
        target_length = max_response_length

    padded_response = [tuple(sub_list) + (pad_token_id,) * (target_length - len(sub_list)) for sub_list in response]
    tensor = torch.tensor(padded_response)
    return tensor