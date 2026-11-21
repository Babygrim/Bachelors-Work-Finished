"""Fold image pre/post-processing into an ONNX super-resolution model.

The wrapped graph takes a uint8 BGR image (NHWC) and returns a uint8 BGR image (NHWC),
so normalisation, channel order, clipping and quantisation run on the GPU instead of
numpy. Results match the CPU implementation exactly (same float32 maths and rounding).
"""

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

INPUT_NAME = "frame"
OUTPUT_NAME = "frame_out"


def wrap_with_image_io(onnx_path):
    """Return serialized ONNX bytes of the model wrapped with uint8 BGR NHWC input/output."""
    model = onnx.load(onnx_path)
    graph = model.graph
    model_input = graph.input[0]
    model_output = graph.output[0]
    in_name, out_name = model_input.name, model_output.name
    model_dtype = model_input.type.tensor_type.elem_type  # FLOAT or FLOAT16
    raw_name = "sr_raw"

    # The original output tensor is produced by some node: redirect it to an internal name.
    for node in graph.node:
        for index, name in enumerate(node.output):
            if name == out_name:
                node.output[index] = raw_name

    def const(name, array):
        return numpy_helper.from_array(np.asarray(array), name)

    graph.initializer.extend([
        const("k_255", np.float32(255.0)),
        const("k_zero", np.float32(0.0)),
        const("k_one", np.float32(1.0)),
        const("k_flip", np.array([2, 1, 0], dtype=np.int64)),
    ])

    pre = [
        helper.make_node("Cast", [INPUT_NAME], ["pre_f32"], to=TensorProto.FLOAT),
        helper.make_node("Div", ["pre_f32", "k_255"], ["pre_unit"]),
        helper.make_node("Gather", ["pre_unit", "k_flip"], ["pre_rgb"], axis=3),
        helper.make_node("Transpose", ["pre_rgb"], ["pre_nchw"], perm=[0, 3, 1, 2]),
    ]
    if model_dtype == TensorProto.FLOAT16:
        pre.append(helper.make_node("Cast", ["pre_nchw"], [in_name], to=TensorProto.FLOAT16))
    else:
        pre.append(helper.make_node("Identity", ["pre_nchw"], [in_name]))

    post = [
        helper.make_node("Cast", [raw_name], ["post_f32"], to=TensorProto.FLOAT),
        helper.make_node("Clip", ["post_f32", "k_zero", "k_one"], ["post_clip"]),
        helper.make_node("Mul", ["post_clip", "k_255"], ["post_scaled"]),
        helper.make_node("Round", ["post_scaled"], ["post_round"]),
        helper.make_node("Cast", ["post_round"], ["post_u8"], to=TensorProto.UINT8),
        helper.make_node("Gather", ["post_u8", "k_flip"], ["post_bgr"], axis=1),
        helper.make_node("Transpose", ["post_bgr"], [OUTPUT_NAME], perm=[0, 2, 3, 1]),
    ]

    new_input = helper.make_tensor_value_info(
        INPUT_NAME, TensorProto.UINT8, [1, "height", "width", 3]
    )
    new_output = helper.make_tensor_value_info(
        OUTPUT_NAME, TensorProto.UINT8, [1, "out_height", "out_width", 3]
    )

    nodes = list(pre) + list(graph.node) + list(post)
    del graph.node[:]
    graph.node.extend(nodes)
    del graph.input[:]
    graph.input.extend([new_input])
    del graph.output[:]
    graph.output.extend([new_output])
    # Stale shape annotations of the replaced tensors would conflict after the rewrite.
    del graph.value_info[:]
    return model.SerializeToString()
