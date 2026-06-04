import customtkinter

DEFAULT_FONT = "Montserrat"
DEFAULT_FONT_SIZE = 18
DEFAULT_FONT_STYLE = "normal"

_FONT = (DEFAULT_FONT, DEFAULT_FONT_SIZE, DEFAULT_FONT_STYLE)
CORNER_RADIUS = 10

SUCCESS_COLOR = '#5cb85c'
SUCCESS_HOVER_COLOR = '#57ab5a'

DANGER_COLOR = '#d9534f'
DANGER_HOVER_COLOR = '#c7504f'

WARNING_COLOR = '#f0ad4e'
WARNING_HOVER_COLOR = '#dca14e'

DEFAULT_COLOR = '#144870'
DEFAULT_HOVER_COLOR = '#1b5685'

BUTTON_COLOR_MAPPING = {
    'success': {
        'default': SUCCESS_COLOR,
        'hover': SUCCESS_HOVER_COLOR
    },
    'warning': {
        'default': WARNING_COLOR,
        'hover': WARNING_HOVER_COLOR,
    },
    'danger': {
        'default': DANGER_COLOR,
        'hover': DANGER_HOVER_COLOR,
    },
    'default': {
        'default': DEFAULT_COLOR,
        'hover': DEFAULT_HOVER_COLOR
    }
}

class StyledCTkButton(customtkinter.CTkButton):
    def __init__(self, master, style='default', **kwargs):
        kwargs.setdefault('bg_color', 'transparent')
        kwargs.setdefault('fg_color', BUTTON_COLOR_MAPPING[style]['default'])
        kwargs.setdefault('hover_color', BUTTON_COLOR_MAPPING[style]['hover'])
        kwargs.setdefault('corner_radius', CORNER_RADIUS / 2)
        kwargs.setdefault('font', (DEFAULT_FONT, DEFAULT_FONT_SIZE))
        kwargs.setdefault('height', 35)
        super().__init__(master=master, **kwargs)

class StyledCTkLabel(customtkinter.CTkLabel):
    def __init__(self, master, style='default', **kwargs):
        kwargs.setdefault('bg_color', 'transparent')
        kwargs.setdefault('fg_color', 'transparent')
        kwargs.setdefault('font', (DEFAULT_FONT, DEFAULT_FONT_SIZE))
        super().__init__(master=master, **kwargs)

class StyledCTkRadio(customtkinter.CTkRadioButton):
    def __init__(self, master, style='default', **kwargs):
        kwargs.setdefault('bg_color', 'transparent')
        kwargs.setdefault('font', (DEFAULT_FONT, DEFAULT_FONT_SIZE))
        kwargs.setdefault('corner_radius', CORNER_RADIUS / 2)
        super().__init__(master=master, **kwargs)

        self.default_padx = 5
        self.default_pady = (5, 0)
        
    def pack(self, **kwargs):
        kwargs.setdefault('padx', self.default_padx)
        kwargs.setdefault('pady', self.default_pady)
        super().pack(**kwargs)

    
def set_styles(self):
    self.style.configure(".", font=_FONT)
    # self.option_add('*TCombobox*Listbox.font', (font, 12))
    # self.option_add('*TCombobox.font', (font, 12))
    # self.option_add('*TEntry.font', (font, 12))
    # self.option_add('*TSpinbox.font', (font, 12))
    
    self.style.configure(
            "*TLabel",
            font=_FONT,
            justify="right",
            
        )
    
    self.style.configure(
            "*Toolbutton",
            font=_FONT,            
        )
    
    self.style.configure(
            "*TButton",
            font=_FONT,
            foreground="blue",
            width=15,
            height=10
    )