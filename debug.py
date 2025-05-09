import customtkinter
from styles import DEFAULT_FONT, DEFAULT_FONT_SIZE

def build_overlay(self):
    try:
        self.overlay.destroy()
    except:
        pass
    self.overlay = customtkinter.CTkFrame(self.canvas_wrapper, width=120, height=30, corner_radius=8, bg_color='transparent')
    self.overlay.place(x=15, y=15)
    
    # Overlay Text
    self.overlay_label = customtkinter.CTkLabel(self.overlay, text="Debug Mode On", text_color="white", font=(DEFAULT_FONT, DEFAULT_FONT_SIZE))
    self.overlay_label.pack(expand=True, fill="both", padx=5, pady=5)

def update_overlay_text(self):
    new_history_object = self.image_history[self.current_image_id]
    self.overlay_label.configure(text=f'''ID: {self.current_image_id}
    Display size: {new_history_object.get('visible_frame_size')}
    Actual size: {new_history_object.get('actual_frame_size')}
    Parent ID: {new_history_object.get('parent_frame_id')}
    Display scale: {new_history_object.get('scale') * 100:.2f}%
    Drag data: {new_history_object.get('drag_data')}
    Relative anchor position data: {new_history_object.get('anchor_data')}''')