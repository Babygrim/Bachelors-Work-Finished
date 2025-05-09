import customtkinter
import tkinter as tk
from styles import (StyledCTkButton, StyledCTkLabel,
                    DEFAULT_FONT, DEFAULT_FONT_SIZE,
                    CORNER_RADIUS)

def add_popup_menu_items(self, menu, suboptions_objects):
    """
    Add a menu item with a dynamic submenu(s) on hover.
    """
    for menu_option in suboptions_objects.keys():
        current_object = suboptions_objects[menu_option]
        
        if isinstance(current_object, dict):
            new_menu_item = tk.Menu(menu, tearoff=0)
            menu.add_cascade(label = menu_option, menu = new_menu_item)
            self.add_popup_menu_items(new_menu_item, current_object)
        else:
            menu.add_command(label = menu_option, command = current_object)
  
# canvas popup logic   
def canvas_popup(self, event):
    self.canvas_menu.post(event.x_root, event.y_root)
    
def canvas_suboption_click(self, suboption):
    """
    Handle clicks on suboptions.
    """
    print(f"Selected: {suboption}")
    
def change_progress_status_text(self, text):
    self.information_label.configure(text=text)

def show_progress_popup(self):
    # Create the popup window
    self.popup = tk.Toplevel(self.root)
    x = self.root.winfo_x() + self.root.winfo_width() // 2 - 150
    y = self.root.winfo_y() + self.root.winfo_height() // 2 - 75
    self.popup.attributes("-topmost", True)
    self.popup.overrideredirect(True)  # No title bar, borderless
    self.popup.deiconify()  # Show the popup after setup
    self.popup.lift()
    #self.popup.focus_force()

    # Optional: re-apply always-on-top periodically (some systems drop it)
    def reinforce_top():
        if self.popup.winfo_exists():
            self.popup.lift()
            self.popup.attributes("-topmost", True)
            self.popup.after(1000, reinforce_top)

    reinforce_top()
    
    self.popup.geometry(f"+{x}+{y}")
        
    # Frame and content
    self.progress_frame = customtkinter.CTkFrame(self.popup, fg_color='#20374c', bg_color='#20374c')
    self.progress_frame.pack(padx=2, pady=2)
    
    # Add the "Processing" text
    self.progress_label = StyledCTkLabel(self.progress_frame, text="Starting thread...")
    self.progress_label.grid(row=0, column=0, padx=10, pady=(5, 0))
    
    # Create the progress bar widget
    self.progress_bar = customtkinter.CTkProgressBar(self.progress_frame, orientation="horizontal", width=300, mode="determinate", corner_radius=CORNER_RADIUS / 2)
    self.progress_bar.set(0)
    self.progress_bar.grid(row=2, column=0, padx=10, pady=10)
    
    self.cancel_progress_button = StyledCTkButton(self.progress_frame, text="Cancel", command=self.cancel_progress)
    self.cancel_progress_button.grid(row=3, column=0, pady=10)
    
def show_error_popup(self, message):
    self.error_popup = tk.Toplevel(self.root)
    self.error_popup.withdraw()  # Hide initially during setup

    # Set error_popup position
    x = self.root.winfo_x() + self.root.winfo_width() // 2 - 150
    y = self.root.winfo_y() + self.root.winfo_height() // 2 - 75
    self.error_popup.geometry(f"+{x}+{y}")

    # Apply attributes to stay on top and borderless
    self.error_popup.attributes("-topmost", True)
    self.error_popup.overrideredirect(True)  # No title bar, borderless
    self.error_popup.deiconify()  # Show the error_popup after setup
    self.error_popup.lift()
    self.error_popup.focus_force()

    # Optional: re-apply always-on-top periodically (some systems drop it)
    def reinforce_top():
        if self.error_popup.winfo_exists():
            self.error_popup.lift()
            self.error_popup.attributes("-topmost", True)
            self.error_popup.after(1000, reinforce_top)

    reinforce_top()

    # Frame and content
    frame = customtkinter.CTkFrame(self.error_popup, fg_color='#20374c', bg_color='#20374c')
    frame.pack(padx=2, pady=2)
    
    message_label = StyledCTkLabel(frame, text="ERROR: " + message, wraplength=300, justify="left")
    message_label.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="w")

    close_button = StyledCTkButton(frame, text="Close", command=self.error_popup.destroy)
    close_button.grid(row=1, column=0, columnspan=2, pady=(0, 10))
    
def show_success_popup(self, message):
    self.success_popup = tk.Toplevel(self.root)
    self.success_popup.withdraw()  # Hide initially during setup

    # Set success_popup position
    x = self.root.winfo_x() + self.root.winfo_width() // 2 - 150
    y = self.root.winfo_y() + self.root.winfo_height() // 2 - 75
    self.success_popup.geometry(f"+{x}+{y}")

    # Apply attributes to stay on top and borderless
    self.success_popup.attributes("-topmost", True)
    self.success_popup.overrideredirect(True)  # No title bar, borderless
    self.success_popup.deiconify()  # Show the success_popup after setup
    self.success_popup.lift()
    self.success_popup.focus_force()

    # Optional: re-apply always-on-top periodically (some systems drop it)
    def reinforce_top():
        if self.success_popup.winfo_exists():
            self.success_popup.lift()
            self.success_popup.attributes("-topmost", True)
            self.success_popup.after(1000, reinforce_top)

    reinforce_top()

    # Frame and content
    frame = customtkinter.CTkFrame(self.success_popup, fg_color='#20374c', bg_color='#20374c')
    frame.pack(padx=2, pady=2)

    message_label = StyledCTkLabel(frame, text="SUCCESS: " + message, wraplength=300, justify="left")
    message_label.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="w")

    close_button = StyledCTkButton(frame, text="Close", command=self.success_popup.destroy)
    close_button.grid(row=1, column=0, columnspan=2, pady=(0, 10))

def show_warning_popup(message):
    def decorator(callback):
        def wrapper(*args, **kwargs):
            self = args[0]

            self.warning_popup = tk.Toplevel(self.root)
            self.warning_popup.withdraw()  # Hide initially during setup

            # Set warning_popup position
            x = self.root.winfo_x() + self.root.winfo_width() // 2 - 150
            y = self.root.winfo_y() + self.root.winfo_height() // 2 - 75
            self.warning_popup.geometry(f"+{x}+{y}")

            self.warning_popup.attributes("-topmost", True)
            self.warning_popup.overrideredirect(True)
            self.warning_popup.deiconify()
            self.warning_popup.lift()
            self.warning_popup.focus_force()

            def reinforce_top():
                if self.warning_popup.winfo_exists():
                    self.warning_popup.lift()
                    self.warning_popup.attributes("-topmost", True)
                    self.warning_popup.after(1000, reinforce_top)

            reinforce_top()

            frame = customtkinter.CTkFrame(self.warning_popup, fg_color='#20374c', bg_color='#20374c')
            frame.pack()

            # Message label centered in the parent frame
            message_label = StyledCTkLabel(
                frame,
                text="WARNING: " + message,
                wraplength=300,
                justify="center"
            )
            message_label.pack(pady=10, padx=5)

            # Buttons container frame
            buttons_frame = customtkinter.CTkFrame(frame, fg_color='transparent')
            buttons_frame.pack(pady=10, padx=5)

            # Continue button
            continue_button = StyledCTkButton(
                buttons_frame,
                text="Continue",
                command=lambda: [self.warning_popup.destroy(), callback(*args, **kwargs)]
            )
            continue_button.pack(side="left", padx=5)

            # Close button
            close_button = StyledCTkButton(
                buttons_frame,
                text="Close",
                command=self.warning_popup.destroy
            )
            close_button.pack(side="right", padx=5)


        return wrapper
    return decorator
