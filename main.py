import ttkbootstrap as ttk
from app import App


if __name__ == "__main__":
    
    root = ttk.Window(themename="superhero")
    root.state("zoomed")
    root.resizable(True, True)
    root.title("Picture Editor")
    root.update()
    app = App(root)
    app.build_Window()
    root.mainloop()