import torch


def load_torch_model(pth_path, scale, num_block=23):
    """Build an eval-mode RRDBNet or SRVGGNetCompact from a Real-ESRGAN .pth checkpoint."""
    loadnet = torch.load(pth_path, map_location='cpu', weights_only=True)
    if 'params_ema' in loadnet:
        state = loadnet['params_ema']
    elif 'params' in loadnet:
        state = loadnet['params']
    else:
        state = loadnet

    if 'body.0.weight' in state:
        from core.models.srvgg_arch import SRVGGNetCompact

        num_feat = state['body.0.weight'].shape[0]
        last = max(int(k.split('.')[1]) for k in state if k.startswith('body.'))
        model = SRVGGNetCompact(
            num_in_ch=3, num_out_ch=3, num_feat=num_feat,
            num_conv=(last - 2) // 2, upscale=scale,
        )
    else:
        from core.models.rrdbnet_arch import RRDBNet

        model = RRDBNet(
            num_in_ch=3, num_out_ch=3, num_feat=64,
            num_block=num_block, num_grow_ch=32, scale=scale,
        )
    model.load_state_dict(state, strict=True)
    model.eval()
    return model
