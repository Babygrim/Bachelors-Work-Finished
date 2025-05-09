import glfw
from OpenGL.GL import *
from PIL import Image
import numpy as np

def glfw_openGL_anti_aliasing(input, progress_bar_queue, sample_rate):
    # === CONFIG ===
    img = input
    samples = int(sample_rate)

    # === Init GLFW ===
    if not glfw.init():
        raise Exception("GLFW init failed")
    
    pil_img = img.convert("RGBA")
    img_width, img_height = pil_img.size
    img_data = np.array(pil_img)[::-1]

    glfw.window_hint(glfw.VISIBLE, False)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.SAMPLES, samples)

    window = glfw.create_window(img_width, img_height, "Offscreen", None, None)
    glfw.make_context_current(window)

    # === Setup OpenGL ===
    glEnable(GL_MULTISAMPLE)
    glViewport(0, 0, img_width, img_height)

    # === Create texture ===
    texture = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, texture)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img_width, img_height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, img_data)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)

    # === Create MSAA framebuffer ===
    fbo_ms = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_ms)

    # Create color renderbuffer with MSAA
    color_rb = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, color_rb)
    glRenderbufferStorageMultisample(GL_RENDERBUFFER, samples, GL_RGBA8, img_width, img_height)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color_rb)

    # Check framebuffer completeness
    assert glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE

    # === Simple shader ===
    vertex_shader = """
    #version 330 core
    out vec2 uv;
    const vec2 verts[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
    void main() {
        uv = (verts[gl_VertexID] + 1.0) / 2.0;
        gl_Position = vec4(verts[gl_VertexID], 0.0, 1.0);
    }
    """

    fragment_shader = """
    #version 330 core
    in vec2 uv;
    out vec4 color;
    uniform sampler2D tex;
    void main() {
        color = texture(tex, uv);
    }
    """

    def compile_shader(src, shader_type):
        shader = glCreateShader(shader_type)
        glShaderSource(shader, src)
        glCompileShader(shader)
        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(shader).decode())
        return shader

    vs = compile_shader(vertex_shader, GL_VERTEX_SHADER)
    fs = compile_shader(fragment_shader, GL_FRAGMENT_SHADER)

    program = glCreateProgram()
    glAttachShader(program, vs)
    glAttachShader(program, fs)
    glLinkProgram(program)
    glUseProgram(program)

    # === Render to MSAA framebuffer ===
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_ms)
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    glBindTexture(GL_TEXTURE_2D, texture)
    glDrawArrays(GL_TRIANGLES, 0, 3)

    # === Blit to normal framebuffer ===
    fbo_resolved = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_resolved)

    # Create a non-multisampled texture for resolved image
    resolved_tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, resolved_tex)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, img_width, img_height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, resolved_tex, 0)

    # Blit from multisampled FBO to resolved FBO
    glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo_ms)
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo_resolved)
    glBlitFramebuffer(0, 0, img_width, img_height,
                    0, 0, img_width, img_height,
                    GL_COLOR_BUFFER_BIT, GL_NEAREST)

    # === Read pixels ===
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_resolved)
    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    data = glReadPixels(0, 0, img_width, img_height, GL_RGBA, GL_UNSIGNED_BYTE)

    # === Save to file ===
    image = Image.frombytes("RGBA", (img_width, img_height), data)
    image = image.transpose(Image.FLIP_TOP_BOTTOM).convert("RGB")
    
    glfw.terminate()

    return image