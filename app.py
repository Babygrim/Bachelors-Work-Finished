import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import ImageEnhance, ImageFilter, Image
from queue import Queue
import img_crop
import img_history
import img_initialization
import img_manipulation
import img_effects
import img_resolution
import app_popups
import app_modes
import img_anti_aliasing
import img_scaling
import process_handlers
from constants import *
import helpers
from styles import *
import time
import os
import customtkinter

class App():
    def __init__(self, root) -> None:
        self.root = root
        
        # init styles
        self.style = ttk.Style()
        
        self.app_icons = {}

        # crop figure selection variables
        self.start_x = None
        self.start_y = None
        self.figure = None
        self.shape_type = "rectangle"
        self.dash_lines = []
        
        # rest of necessary shit
        self.image_history = dict()
        self.unfiltered_images = dict()
        self.current_image_id = DEFAULT_IMAGE_ID
        self.current_app_module = DEFAULT_LOAD_MODULE
        self.canvas_popup_menu = None
        self.last_zoomed = time.time()
        self.zoom_factor = 0.15
        
        self.app_modules = {
            "Image_Effects": {"loader": self.build_Image_Effects_module, "state": True},
            "Resolution_Enhancement": {"loader": self.build_Resolution_Enhancement_module, "state": True}
        }
        self.app_modules_btns = {
            "Image_Effects": {"caller": self.build_Image_Effects_button},
            "Resolution_Enhancement": {"caller": self.build_Resolution_Enhancement_button}
        }
        
        self.app_methods = {}
        
    def load_module(self, module_name):
        self.save_history(module=self.current_app_module)
        loader = self.app_modules[module_name]['loader']
        loader()
        
        self.current_app_module = module_name
        self.load_module_settings(self.current_image_id, self.current_app_module)
        #self.set_styles()
    
    def build_app_tools(func):
        def wrapper(*args, **kwargs):
            self = args[0]
            
            func(*args, **kwargs)
            self.reset_button = StyledCTkButton(self.module_toolframe, style="warning", text="Reset effects", image=self.app_icons["reset"], compound=LEFT, command=self.load_unchanged_image)
            self.reset_button.pack(fill="x", padx=5, pady=5)
        
        return wrapper
    
    def load_icons(self):
        for filename in os.listdir(ICONS_DIRECTORY):
            f = os.path.join(ICONS_DIRECTORY, filename)
            if os.path.isfile(f):
                icon = Image.open(f)
                resized, _ = self.resize_image(icon, new_height=16, new_width=16)
                name = filename.split('.')[0]
                self.app_icons[name] = customtkinter.CTkImage(resized)
        
    def build_canvas(self):
        self.canvas = tk.Canvas(self.canvas_wrapper, height=200, width=200)
        self.canvas.pack(fill="none", expand=True, padx=5, pady=5)
        
        # button
        self.add_pic_button = StyledCTkButton(self.canvas, style="success", text="Import image", command=self.get_image, width=150)
        self.add_pic_button.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # right click menu stuff
        # self.canvas_menu = tk.Menu(self.canvas, tearoff=0, activeborderwidth=0, borderwidth=1)
        
        # # Add menu items with hover functionality
        # self.add_popup_menu_items(self.canvas_menu, {"Crop Image": {"Rectangular": lambda: self.choose_crop_shape("rectangle"), 
        #                                                      "Round": lambda: self.choose_crop_shape("circle"), 
        #                                                      "Polygon": lambda: self.choose_crop_shape("polygon")}})
        
        # self.canvas.bind("<Button-3>", self.canvas_popup)
    
    def build_history_frame(self):
        """Builds the history frame with a scrollable canvas for thumbnails."""
        # Wrapper frame for history
        self.history_wrapper = ttk.Frame(self.root)
        self.history_wrapper.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.history_wrapper.grid_propagate(False)
        self.history_wrapper.pack_propagate(False)

        self.photo_frame_extra = customtkinter.CTkScrollableFrame(self.history_wrapper, fg_color="#20374c",
                                                                  scrollbar_button_color="#273d52",
                                                                  scrollbar_button_hover_color="#2f485e")
        self.photo_frame_extra.pack(fill="both", expand=True)
        
    def build_image_toolframe(self):
        self.image_toolbar = customtkinter.CTkFrame(self.main_frame, height=50, corner_radius=CORNER_RADIUS, bg_color='transparent')
        self.image_toolbar.grid(row=1, column=0, sticky="nsew")
        self.image_toolbar.grid_propagate(False)
        self.image_toolbar.pack_propagate(False)
        
        self.save_pic_button = StyledCTkButton(self.image_toolbar, style='success', text="Export image", command=self.save_image, state=tk.DISABLED)
        self.save_pic_button.pack(fill="none", padx=10, pady=5, side='left')
        
        self.remove_pic_button = StyledCTkButton(self.image_toolbar, text="Remove image", command=self.remove_image, state=tk.DISABLED, style="danger")
        self.remove_pic_button.pack(fill="none", padx=0, pady=5, side='left')
        
        self.scale_slider = customtkinter.CTkSlider(self.image_toolbar, width=150, from_=10, to=500)
        self.scale_slider.pack(fill='none', padx=10, pady=5, side='right')

        self.scale_label = StyledCTkLabel(self.image_toolbar, text="Scale")
        self.scale_label.pack(fill='none', padx=10, pady=5, side='right')
        
        self.reset_scale_button = StyledCTkButton(self.image_toolbar, command=self.reset_scale, style="warning", text="", image=self.app_icons["reset"], width=0)
        self.reset_scale_button.pack(fill='none', padx=0, pady=5, side='right')
        
    #build Image Effects module
    @build_app_tools
    def build_Image_Effects_module(self):
        _ModuleName = "Image_Effects"
        
        # clear space
        for child in self.module_toolframe.winfo_children():
            child.destroy()
        
        # update to populate changes    
        self.module_toolframe.update()
        
        # effects
        inversion_bound_variable = tk.BooleanVar()
        self.invert_colors = customtkinter.CTkSwitch(self.module_toolframe, text="Invert Image Colors (OFF)", 
                                                     onvalue=DEFAULT_SWITCH_METHOD_ON_VALUE, 
                                                     offvalue=DEFAULT_SWITCH_METHOD_OFF_VALUE, 
                                                     variable=inversion_bound_variable, 
                                                     bg_color="transparent", 
                                                     font=(DEFAULT_FONT, DEFAULT_FONT_SIZE),
                                                )
        self.invert_colors.configure(command = lambda: self.modify_image(values={
                                                                                'switch': [(inversion_bound_variable,)],
                                                                                'slider': [],
                                                                                'checkbox': []
                                                                                }, 
                                                                         function=img_effects.invert_image_colors, 
                                                                         text_value=("Invert Image Colors", self.invert_colors), 
                                                                         type="switch"))
        self.invert_colors.pack(fill="x", padx=5, pady=10)
        
        # sliders
        
        # gamma slider
        gamma_bound_variable = tk.IntVar(value=DEFAULT_SLIDER_VALUES["Brightness"])
        self.g_slider = StyledCTkLabel(self.module_toolframe, text="Brightness (1.00)")
        self.gamma_selector = customtkinter.CTkSlider(self.module_toolframe, from_=0, to=500,  orientation=tk.HORIZONTAL, width=150, variable=gamma_bound_variable)
        self.gamma_selector.configure(command = lambda value: self.modify_image(values={
                                                                                'switch': [],
                                                                                'slider': [(gamma_bound_variable,)],
                                                                                'checkbox': []
                                                                                }, 
                                                                                function=ImageEnhance.Brightness, 
                                                                                text_value=("Brightness", self.g_slider), 
                                                                                type="slider"))
        self.gamma_selector.set(DEFAULT_SLIDER_VALUES["Brightness"])
        self.g_slider.pack(fill="x", padx=5, pady=(10, 0))
        self.gamma_selector.pack(fill="x", padx=5, pady=5)
        
        # color slider
        color_bound_variable = tk.IntVar(value=DEFAULT_SLIDER_VALUES["Color"])
        self.cl_slider = StyledCTkLabel(self.module_toolframe, text="Color (1.00)")
        self.color_selector = customtkinter.CTkSlider(self.module_toolframe, from_=0, to=500,  orientation=tk.HORIZONTAL, width=150, variable=color_bound_variable)
        self.color_selector.configure(command = lambda value: self.modify_image(values={
                                                                                'switch': [],
                                                                                'slider': [(color_bound_variable,)],
                                                                                'checkbox': []
                                                                                }, 
                                                                                function=ImageEnhance.Color, 
                                                                                text_value=("Color", self.cl_slider), 
                                                                                type="slider"))
        self.color_selector.set(DEFAULT_SLIDER_VALUES["Color"])
        self.cl_slider.pack(fill="x", padx=5, pady=(10, 0))
        self.color_selector.pack(fill="x", padx=5, pady=5)
        
        # contrast slider
        contrast_bound_variable = tk.IntVar(value=DEFAULT_SLIDER_VALUES["Contrast"])
        self.con_slider = StyledCTkLabel(self.module_toolframe, text="Contrast (1.00)")
        self.contrast_selector = customtkinter.CTkSlider(self.module_toolframe, from_=0, to=500, orientation=tk.HORIZONTAL, width=150, variable=contrast_bound_variable)
        self.contrast_selector.configure(command = lambda value: self.modify_image(values={
                                                                                    'switch': [],
                                                                                    'slider': [(contrast_bound_variable,)],
                                                                                    'checkbox': []
                                                                                    },
                                                                                   function=ImageEnhance.Contrast, 
                                                                                   text_value=("Contrast", self.con_slider), 
                                                                                   type="slider"))
        self.contrast_selector.set(DEFAULT_SLIDER_VALUES["Contrast"])
        self.con_slider.pack(fill="x", padx=5, pady=(10, 0))
        self.contrast_selector.pack(fill="x", padx=5, pady=5)
        
        # sharpness slider
        shrp_bound_variable = tk.IntVar(value=DEFAULT_SLIDER_VALUES["Sharpness"])
        self.shrp_slider = StyledCTkLabel(self.module_toolframe, text="Sharpness (1.00)")
        self.sharpness_selector = customtkinter.CTkSlider(self.module_toolframe, from_=-500, to=500,orientation=tk.HORIZONTAL, width=150, variable=shrp_bound_variable)
        self.sharpness_selector.configure(command = lambda value: self.modify_image(values={
                                                                                    'switch': [],
                                                                                    'slider': [(shrp_bound_variable,)],
                                                                                    'checkbox': []
                                                                                    }, 
                                                                                    function=ImageEnhance.Sharpness, 
                                                                                    text_value=("Sharpness", self.shrp_slider), 
                                                                                    type="slider"))
        self.sharpness_selector.set(DEFAULT_SLIDER_VALUES["Sharpness"])
        self.shrp_slider.pack(fill="x", padx=5, pady=(10, 0))
        self.sharpness_selector.pack(fill="x", padx=5, pady=5)
        
        # blur filter
        blur_bound_variable = tk.IntVar(value=DEFAULT_SLIDER_VALUES["Blur"])
        self.blur_slider = StyledCTkLabel(self.module_toolframe, text="Blur (0.00)")
        self.blur_selector = customtkinter.CTkSlider(self.module_toolframe, from_=0, to=1000,orientation=tk.HORIZONTAL, width=150, variable=blur_bound_variable)
        self.blur_selector.configure(command = lambda value: self.modify_image(values={
                                                                                'switch': [],
                                                                                'slider': [(blur_bound_variable,)],
                                                                                'checkbox': []
                                                                                }, 
                                                                               function=ImageFilter.GaussianBlur, 
                                                                               text_value=("Blur", self.blur_slider), 
                                                                               type="slider"))
        self.blur_selector.set(DEFAULT_SLIDER_VALUES["Blur"])
        self.blur_slider.pack(fill="x", padx=5, pady=(10, 0))
        self.blur_selector.pack(fill="x", padx=5, pady=5)
        
        # Integrate into App class
        sliders = {
            "Brightness": (ImageEnhance.Brightness, {
                                                    'switch': [],
                                                    'slider': [(gamma_bound_variable, )],
                                                    'checkbox': []
                                                    }, {
                                                    'switch': [],
                                                    'slider': [("Brightness", self.g_slider)],
                                                    'checkbox': []
                                                    }),
            
            "Color": (ImageEnhance.Color, {
                                            'switch': [],
                                            'slider': [(color_bound_variable, )],
                                            'checkbox': []
                                            }, {
                                            'switch': [],
                                            'slider': [("Color", self.cl_slider)],
                                            'checkbox': []
                                            }),
            
            "Contrast": (ImageEnhance.Contrast, {
                                                'switch': [],
                                                'slider': [(contrast_bound_variable, )],
                                                'checkbox': []
                                                }, {
                                                'switch': [],
                                                'slider': [("Contrast", self.con_slider)],
                                                'checkbox': []
                                                }),
            
            "Sharpness": (ImageEnhance.Sharpness, {
                                                    'switch': [],
                                                    'slider': [(shrp_bound_variable, )],
                                                    'checkbox': []
                                                    }, {
                                                    'switch': [],
                                                    'slider': [("Sharpness", self.shrp_slider)],
                                                    'checkbox': []
                                                    }),
            "Blur": (ImageFilter.GaussianBlur, {
                                                'switch': [],
                                                'slider': [(blur_bound_variable, )],
                                                'checkbox': []
                                                }, {
                                                'switch': [],
                                                'slider': [("Blur", self.blur_slider)],
                                                'checkbox': []
                                                }),
        }
        
        switches = {
            "Inversion": (img_effects.invert_image_colors, {
                                                    'switch': [(inversion_bound_variable, )],
                                                    'slider': [],
                                                    'checkbox': []
                                                    }, {
                                                    'switch': [("Invert Image Colors", self.invert_colors)],
                                                    'slider': [],
                                                    'checkbox': []
                                                    }),
        }    
        
        callers = {
        }
        
        self.app_methods[_ModuleName] = {
            "slider_methods": sliders,
            "switch_methods": switches,
            "selector_methods": {},
            "caller_methods": callers,
        }
    
    def build_Image_Effects_button(self, state):
        return StyledCTkButton(self.top_toolbar, text="Image Effects", command=lambda: self.load_module("Image_Effects"), state=state, width=150)
        
    #build Resolution Enhancement module
    @build_app_tools
    def build_Resolution_Enhancement_module(self):
        _ModuleName = "Resolution_Enhancement"
        
        for child in self.module_toolframe.winfo_children():
            child.destroy()
        
        AI_res_vals = {'1x': 1,
                       '2x': 2,
                       '4x': 4}
        
        sample_factor_MSAA = tk.IntVar()
        upscale_factor = tk.IntVar()
        model = tk.StringVar()
        image_scale_variable = tk.BooleanVar()
        facial_restoration_variable = tk.BooleanVar()
        upscale_factor_two = tk.IntVar()
        sample_factor_two = tk.IntVar()
        
        sample_factor_MSAA.set(DEFAULT_RESOLUTION_VALUES["2x"])
        upscale_factor.set(AI_res_vals["1x"])
        image_scale_variable.set(False)
        upscale_factor_two.set(DEFAULT_RESOLUTION_VALUES["2x"])
        sample_factor_two.set(DEFAULT_RESOLUTION_VALUES["2x"])
        
        
        # self.msaa_label = StyledCTkLabel(self.module_toolframe, text="Select sampling factor")
        # self.msaa_label.pack(fill=X, padx=5, pady=(10, 0))
        # for (text, value) in DEFAULT_RESOLUTION_VALUES.items():
        #     StyledCTkRadio(self.module_toolframe, text = text, variable=sample_factor_MSAA, 
        #                 value = value).pack(fill=X, padx=5, pady=(5, 0))
        
        # self.perform_multisample = StyledCTkButton(self.module_toolframe, text="MSAA", command=lambda: self.modify_image(values={
        #                                                                                                                     'switch': [],
        #                                                                                                                     'slider': [],
        #                                                                                                                     'checkbox': [(sample_factor_MSAA, )]
        #                                                                                                                     }, 
        #                                                                                                                  function=img_resolution.multisampling, 
        #                                                                                                                  text_value=None, 
        #                                                                                                                  type="processing"))
        # self.perform_multisample.pack(fill=X, padx=5, pady=5)

        self.upscale_label = StyledCTkLabel(self.module_toolframe, text="Select upscale factor")
        self.upscale_label.pack(fill=X, padx=5, pady=(10, 0))
        
        self.model_combobox = customtkinter.CTkOptionMenu(self.module_toolframe,
                                                        dropdown_fg_color=DEFAULT_COLOR,
                                                        dropdown_hover_color=DEFAULT_HOVER_COLOR,
                                                        variable=model,
                                                        width=200,
                                                        fg_color=DEFAULT_COLOR,
                                                        corner_radius=CORNER_RADIUS,
                                                        bg_color=DEFAULT_COLOR,
                                                        button_hover_color=DEFAULT_HOVER_COLOR,
                                                        font=(DEFAULT_FONT, DEFAULT_FONT_SIZE * 0.75),
                                                        dropdown_font=(DEFAULT_FONT, DEFAULT_FONT_SIZE * 0.75),
                                                        state=READONLY)
        
        def change_models_list(combobox, variable, switch):
            values_list = list(item.removesuffix('.pth') for item in filter(lambda key: key.startswith(str(variable.get())), os.listdir(ROOT_DIR + "/weights")))
            combobox.configure(values=values_list)
            combobox.set(values_list[0])
            if variable.get() == 1:
                switch.configure(state='disabled', text="Keep original size (OFF)")
                image_scale_variable.set(False)
            else:
                switch.configure(state='normal')            
            
        self.image_scale_switch = customtkinter.CTkSwitch(self.module_toolframe, text="Keep original size (OFF)", 
                                                     onvalue=DEFAULT_SWITCH_METHOD_ON_VALUE, 
                                                     offvalue=DEFAULT_SWITCH_METHOD_OFF_VALUE, 
                                                     variable=image_scale_variable, 
                                                     bg_color="transparent", 
                                                     font=(DEFAULT_FONT, DEFAULT_FONT_SIZE))
        
        self.facial_enhancement_switch = customtkinter.CTkSwitch(self.module_toolframe, text="Facial restoration (OFF)", 
                                                     onvalue=DEFAULT_SWITCH_METHOD_ON_VALUE, 
                                                     offvalue=DEFAULT_SWITCH_METHOD_OFF_VALUE, 
                                                     variable=facial_restoration_variable, 
                                                     bg_color="transparent", 
                                                     font=(DEFAULT_FONT, DEFAULT_FONT_SIZE))
        
        for (text, value) in AI_res_vals.items():
            StyledCTkRadio(self.module_toolframe, text = text, variable=upscale_factor, 
                        value = value,
                        command=lambda: change_models_list(self.model_combobox, upscale_factor, self.image_scale_switch)).pack(fill=X, padx=5, pady=(5, 0))
        
        
        self.image_scale_switch.pack(fill="x", padx=5, pady=5)
        self.facial_enhancement_switch.pack(fill="x", padx=5, pady=5)
        
        self.model_combobox.pack(fill="x", padx=5, pady=5)
        change_models_list(self.model_combobox, upscale_factor, self.image_scale_switch)
        
        self.image_scale_switch.configure(command=lambda: self.modify_image(values={
                                                                                    'switch': [(image_scale_variable, )],
                                                                                    'slider': [],
                                                                                    'checkbox': []
                                                                                    }, 
                                                                                    function=None,
                                                                                    text_value=("Keep original size", self.image_scale_switch), 
                                                                                    type="helper"))
        
        self.facial_enhancement_switch.configure(command=lambda: self.modify_image(values={
                                                                                    'switch': [(facial_restoration_variable, )],
                                                                                    'slider': [],
                                                                                    'checkbox': []
                                                                                    }, 
                                                                                    function=None,
                                                                                    text_value=("Facial restoration", self.facial_enhancement_switch), 
                                                                                    type="helper"))
        
        
        self.perform_upscale = StyledCTkButton(self.module_toolframe, text="Real-ESRGAN", command=lambda: self.modify_image(values={
                                                                                                                            'switch': [(image_scale_variable, ), (model, ), (facial_restoration_variable, )],
                                                                                                                            'slider': [],
                                                                                                                            'checkbox': [(upscale_factor, )]
                                                                                                                            }, 
                                                                                                                         function=img_resolution.upscale_image, 
                                                                                                                         text_value=None, 
                                                                                                                         type="processing"))
        self.perform_upscale.pack(fill=X, padx=5, pady=5)
        
        # self.upscale_label_two = StyledCTkLabel(self.module_toolframe, text="Select upscale factor")
        # self.upscale_label_two.pack(fill=X, padx=5, pady=(10, 0))
        
        # for (text, value) in DEFAULT_RESOLUTION_VALUES.items():
        #     StyledCTkRadio(self.module_toolframe, text = text, variable = upscale_factor_two, 
        #                 value = value).pack(fill=X, padx=5, pady=(5, 0))
        
        # self.perform_upscale_two = StyledCTkButton(self.module_toolframe, text="cv2 upscale", command=lambda: self.modify_image(values={
        #                                                                                                                     'switch': [],
        #                                                                                                                     'slider': [],
        #                                                                                                                     'checkbox': [(upscale_factor_two, )]
        #                                                                                                                     }, 
        #                                                                                                                  function=img_resolution.upscale_cv2, 
        #                                                                                                                  text_value=None, 
        #                                                                                                                  type="processing"))
        # self.perform_upscale_two.pack(fill=X, padx=5, pady=5)
        
        # self.upscale_label_three = StyledCTkLabel(self.module_toolframe, text="Select sampling factor")
        # self.upscale_label_three.pack(fill=X, padx=5, pady=(10, 0))
        
        # for (text, value) in DEFAULT_RESOLUTION_VALUES.items():
        #     StyledCTkRadio(self.module_toolframe, text = text, variable = sample_factor_two, 
        #                 value = value).pack(fill=X, padx=5, pady=(5, 0))
        
        # self.perform_multisample_two = StyledCTkButton(self.module_toolframe, text="GFLW/OpenGL sampling", command=lambda: self.modify_image(values={
        #                                                                                                                     'switch': [],
        #                                                                                                                     'slider': [],
        #                                                                                                                     'checkbox': [(sample_factor_two, )]
        #                                                                                                                     }, 
        #                                                                                                                  function=img_anti_aliasing.glfw_openGL_anti_aliasing, 
        #                                                                                                                  text_value=None, 
        #                                                                                                                  type="processing"))
        # self.perform_multisample_two.pack(fill=X, padx=5, pady=5)
        
        
        # deblur_kernel_variable = tk.IntVar(value=200)
        # self.deblur_slider = StyledCTkLabel(self.module_toolframe, text="Deblur Kernel Size (2.00)")
        # self.deblur_selector = customtkinter.CTkSlider(self.module_toolframe, from_=100, to=1000, orientation=tk.HORIZONTAL, width=150, number_of_steps=9, variable=deblur_kernel_variable)
        # self.deblur_selector.configure(command = lambda value: self.modify_image(values={
        #                                                                             'switch': [],
        #                                                                             'slider': [(deblur_kernel_variable, )],
        #                                                                             'checkbox': []
        #                                                                             }, 
        #                                                                          function=None, 
        #                                                                          text_value=("Deblur Kernel Size", self.deblur_slider), 
        #                                                                          type='helper')) # this is done simply to update label text (part of modify image functionality)
        # self.deblur_selector.set(DEFAULT_SLIDER_VALUES['Deblur'])
        # self.deblur_slider.pack(fill="x", padx=5, pady=(10, 0))
        # self.deblur_selector.pack(fill="x", padx=5, pady=5)
        
        # self.deblur_image = StyledCTkButton(self.module_toolframe, text="Deblur Image", command=lambda: self.modify_image(values={
        #                                                                                                                     'switch': [],
        #                                                                                                                     'slider': [], # (deblur_kernel_variable, )
        #                                                                                                                     'checkbox': []
        #                                                                                                                     }, 
        #                                                                                                                     function=img_effects.deblur_image_wiener, 
        #                                                                                                                     text_value=None, 
        #                                                                                                                     type="processing"))
        # self.deblur_image.pack(fill="x", padx=5, pady=(10, 0))
        
        self.denoise = StyledCTkButton(self.module_toolframe, text="Denoise", command=lambda: self.modify_image(values={
                                                                                                                'switch': [],
                                                                                                                'slider': [],
                                                                                                                'checkbox': []
                                                                                                                }, 
                                                                                                                function=img_resolution.denoise_image_pil, 
                                                                                                                text_value=None, 
                                                                                                                type="processing"))
        self.denoise.pack(fill=X, padx=5, pady=10)
        
        # Integrate into App class
        selectors = {
            # "MSAA_one": (img_resolution.multisampling, {
            #                                         'switch': [],
            #                                         'slider': [],
            #                                         'checkbox': [(sample_factor_MSAA, )]
            #                                         }, None),
            "AI_UPSCALE": (img_resolution.upscale_image, {
                                                    'switch': [(image_scale_variable, facial_restoration_variable)],
                                                    'slider': [],
                                                    'checkbox': [(upscale_factor, )]
                                                    }, {
                                                        'switch': [("Keep original size", self.image_scale_switch), ("Facial restoration", self.facial_enhancement_switch)],
                                                        'slider': [],
                                                        'checkbox': [],
                                                    }),
            # "UPSCALE_two": (img_resolution.upscale_cv2, {
            #                                         'switch': [],
            #                                         'slider': [],
            #                                         'checkbox': [(upscale_factor_two, )]
            #                                         }, None),
            
            # "MSAA_two": (img_anti_aliasing.glfw_openGL_anti_aliasing, {
            #                                         'switch': [],
            #                                         'slider': [],
            #                                         'checkbox': [(sample_factor_two, )]
            #                                         }, None),
        }
        
        callers = {
            'Denoise': (img_resolution.denoise_image_pil, {
                            'switch': [],
                            'slider': [],
                            'checkbox': []
                        }, {
                            'switch': [],
                            'slider': [],
                            'checkbox': [],
                        }),
            # "Deblur": (img_effects.deblur_image_wiener, 
            #            {
            #                 'switch': [],
            #                 'slider': [],
            #                 'checkbox': [] # (deblur_kernel_variable, )
            #             }, {
            #                 'switch': [],
            #                 'slider': [], # ("Deblur Kernel Size", self.deblur_slider)
            #                 'checkbox': [],
            #             }),
        }
        
        self.app_methods[_ModuleName] = {
            "slider_methods": {},
            "switch_methods": {},
            "selector_methods": selectors,
            "caller_methods": callers,
        }

    def build_Resolution_Enhancement_button(self, state):
        return StyledCTkButton(self.top_toolbar, text="Image Enhancement", command=lambda: self.load_module("Resolution_Enhancement"), state=state, width=150)
    
    def build_Window(self):
        # load icons
        self.load_icons()
        
        # main frame
        # Configure the root grid to adjust proportions
        self.root.rowconfigure(1, weight=1)  # Main content area
        self.root.columnconfigure(1, weight=110)  # Main column
        self.root.columnconfigure(0, weight=30)  # Left column
        self.root.columnconfigure(2, weight=5)  # Right column
        self.root.config(padx=10, pady=10)
        
        # Top toolbar
        self.top_toolbar = customtkinter.CTkFrame(self.root, height=50, corner_radius=CORNER_RADIUS, bg_color='transparent')
        self.top_toolbar.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=5, pady=5)
        self.top_toolbar.grid_propagate(False)
        
        # Left column
        self.build_history_frame()
        
        # Main column
        self.main_frame = customtkinter.CTkFrame(self.root, bg_color='transparent', fg_color='transparent')
        self.main_frame.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        self.main_frame.rowconfigure(0, weight=100)  # Image display area
        self.main_frame.rowconfigure(1, weight=1)  # Image-specific toolbar
        self.main_frame.columnconfigure(0, weight=1)  # Make sure components stretch horizontally
        self.main_frame.grid_propagate(False)
        self.main_frame.pack_propagate(False)
        
        # Image display area
        self.canvas_wrapper = customtkinter.CTkFrame(self.main_frame, bg_color='transparent', fg_color='transparent')
        self.canvas_wrapper.grid(row=0, column=0, sticky="nsew")
        self.canvas_wrapper.grid_propagate(False)
        self.canvas_wrapper.pack_propagate(False)
        
        # Canvas area - image holder
        self.build_canvas()
                
        # Image-specific toolbar
        self.build_image_toolframe()
        
        # Right column
        self.module_toolframe = customtkinter.CTkScrollableFrame(self.root, fg_color="#20374c",
                                                                  scrollbar_button_color="#273d52",
                                                                  scrollbar_button_hover_color="#2f485e")
        self.module_toolframe.grid(row=1, column=2, sticky="nsew", padx=5, pady=5, ipadx=10, ipady=10)
        self.module_toolframe.rowconfigure(0, weight=1)  # Allow components to expand vertically        
        # self.module_toolframe.grid_propagate(False)
        # self.module_toolframe.pack_propagate(False)
        
        self.add_pic_button_top = StyledCTkButton(self.top_toolbar, style="success", text="Import image", command=self.get_image, width=150)
        self.add_pic_button_top.pack(fill=None, padx=5, pady=5, side=LEFT)
        
        # load module buttons
        for module in self.app_modules.keys():
            state = 'active' if self.app_modules[module]['state'] else 'disable'

            btn_builder = self.app_modules_btns[module]['caller']
            btn = btn_builder(state)
            btn.pack(fill=None, padx=5, pady=5, side=LEFT)
            btn.pack_propagate(True)
        
        # load styles
        self.set_styles()
        
        # loads app in either dev or prod regime
        self.appMODE()
        
        # load initial module
        self.load_module(self.current_app_module)
        
        # app is initially uninteractable
        self.disable_app_tools()
        

#binding image_crop methods  
App.start_selection = img_crop.start_selection
App.update_selection = img_crop.update_selection
App.finalize_selection = img_crop.finalize_selection
App.interrupt_crop = img_crop.interrupt_crop

#binding history methods
App.build_history = img_history.build_history
App.load_history = img_history.load_history
App.save_history = img_history.save_history

#binding image_initialization methods
App.get_image = img_initialization.get_image
App.remove_image = img_initialization.remove_image
App.save_image = img_initialization.save_image

#binding image manipulation methods
App.display_image = img_manipulation.display_image
App.modify_image = img_manipulation.modify_image
App.resize_image = img_manipulation.resize_image
App.apply_settings = img_manipulation.apply_settings

#helper functions
App.load_module_settings = helpers.load_module_settings
App.change_items_state = helpers.change_items_state
App.reset_module_tools = helpers.reset_module_tools
App.load_unchanged_image = helpers.load_unchanged_image
App.display_on_canvas = helpers.display_on_canvas
App.disable_app_tools = helpers.disable_app_tools
App.enable_app_tools = helpers.enable_app_tools
App.generate_function_arguments = helpers.generate_function_arguments
App.update_scale = helpers.update_scale
App.set_styles = set_styles

#image scaling
App.zoom = img_scaling.zoom
App.start_drag = img_scaling.start_drag
App.do_drag = img_scaling.do_drag
App.keep_image_in_bounds = img_scaling.keep_image_in_bounds
App.update_scroll_region = img_scaling.update_scroll_region
App.move_image = img_scaling.move_image
App.apply_zoom = img_scaling.apply_zoom
App.reset_scale = img_scaling.reset_scale
App.zoom_slider = img_scaling.zoom_slider

# CANVAS RELATED POP UPS
#popups
App.add_popup_menu_items = app_popups.add_popup_menu_items
#canvas popups logic
App.canvas_popup = app_popups.canvas_popup
App.canvas_suboption_click= app_popups.canvas_suboption_click

# RESOLUTION ENHANCEMENT PROCESS HANDLERS
App.show_progress_popup = app_popups.show_progress_popup
App.show_error_popup = app_popups.show_error_popup
App.change_progress_status_text = app_popups.change_progress_status_text
App.show_success_popup = app_popups.show_success_popup

App.cancel_progress = process_handlers.cancel_progress
App.image_processing_wrapper = process_handlers.image_processing_wrapper
App.start_processing = process_handlers.start_processing
App.run_processing_pipeline = process_handlers.run_processing_pipeline
App.check_process_result = process_handlers.check_process_result
App.check_progress = process_handlers.check_progress
App.update_progress = process_handlers.update_progress

#select app mode dev or prod
if DEBUG:
    App.appMODE = app_modes.turnDEBUGmodeOn
    import debug
    App.update_overlay_text = debug.update_overlay_text
    App.build_overlay = debug.build_overlay
else:
    App.appMODE = app_modes.turnDEBUGmodeOff