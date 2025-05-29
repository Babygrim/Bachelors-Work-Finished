# # # # import tkinter as tk

# # # # def populate_frame(frame):
# # # #     """Populate the frame with sample widgets to demonstrate scrolling."""
# # # #     for i in range(50):
# # # #         tk.Label(frame, text=f"Label {i}").pack()

# # # # # Create the main window
# # # # root = tk.Tk()
# # # # root.geometry("400x300")

# # # # # Create a canvas and a scrollbar
# # # # canvas = tk.Canvas(root)
# # # # scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)

# # # # # Pack canvas and scrollbar
# # # # canvas.pack(side="left", fill="both", expand=True)
# # # # scrollbar.pack(side="right", fill="y")

# # # # # Create a frame inside the canvas
# # # # frame = tk.Frame(canvas)

# # # # # Add the frame to the canvas window
# # # # frame_id = canvas.create_window((0, 0), window=frame, anchor="nw")

# # # # # Configure the scrollbar with the canvas
# # # # canvas.configure(yscrollcommand=scrollbar.set)

# # # # # Populate the frame with widgets
# # # # populate_frame(frame)

# # # # # Update the scroll region of the canvas whenever the frame changes size
# # # # def configure_frame(event):
# # # #     canvas.configure(scrollregion=canvas.bbox("all"))

# # # # frame.bind("<Configure>", configure_frame)

# # # # # Allow scrolling with the mouse wheel
# # # # def on_mousewheel(event):
# # # #     canvas.yview_scroll(-1 * int(event.delta / 120), "units")

# # # # canvas.bind_all("<MouseWheel>", on_mousewheel)

# # # # # Run the application
# # # # root.mainloop()

# # import cv2
# # import torch
# # from torchvision.transforms import ToTensor, ToPILImage
# # import torch.nn as nn
# # import torchvision.transforms as transforms
# # import numpy as np
# # from PIL import Image

# # # Простий SRCNN (Super Resolution Convolutional Neural Network)
# # class SRCNN(nn.Module):
# #     def __init__(self):
# #         super(SRCNN, self).__init__()
# #         self.conv1 = nn.Conv2d(3, 64, kernel_size=(9, 9), stride=(1, 1), padding=(2, 2))
# #         self.conv2 = nn.Conv2d(64, 32, kernel_size=(1, 1), stride=(1, 1), padding=(2, 2))
# #         self.conv3 = nn.Conv2d(32, 3, kernel_size=(5, 5), stride=(1, 1), padding=(2, 2))
# #         self.relu = nn.ReLU(inplace=True)
    
# #     def forward(self, x):
# #         x = self.relu(self.conv1(x))
# #         x = self.relu(self.conv2(x))
# #         x = self.conv3(x)
# #         return x

# # # Завантаження попередньо навченого SRCNN (або навчіть його на своєму датасеті)
# # def load_model(scale):
# #     model = SRCNN()
# #     model.load_state_dict(torch.load(f"./weights/model_{scale}x.pth", map_location=torch.device('cpu')))
# #     model.eval()
# #     return model

# # # Функція апскейлу зображення
# # def upscale_image(image_path, scale_factor=2, output_path="upscaled_image.png"):
# #     # Завантаження зображення
# #     image = cv2.imread(image_path)
# #     image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
# #     # Масштабування (до низької якості, для тестування)
# #     low_res = cv2.resize(image, None, fx=1/scale_factor, fy=1/scale_factor, interpolation=cv2.INTER_LINEAR)
# #     low_res = cv2.resize(low_res, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_LINEAR)

# #     # Завантаження моделі
# #     model = load_model(scale = scale_factor)

# #     # Перетворення у тензор
# #     transform = transforms.Compose([ToTensor()])
# #     input_tensor = transform(low_res).unsqueeze(0)

# #     # Апскейл через модель
# #     with torch.no_grad():
# #         output = model(input_tensor)

# #     # Перетворення у зображення
# #     output_image = ToPILImage()(output.squeeze(0).clamp(0, 1))
# #     output_image.save(output_path)
# #     return np.array(output_image), low_res

# # # Використання
# # image_path = "./TEST_IMAGES/sas-geospatial-TerraColor-NextGen-aerial-image.jpg"  # Вкажіть шлях до зображення
# # output_path = "upscaled_image.jpg"
# # upscaled_image, low_res = upscale_image(image_path, output_path=output_path)

# # # Візуалізація результатів
# # import matplotlib.pyplot as plt

# # plt.figure(figsize=(15, 10))

# # plt.subplot(1, 3, 1)
# # plt.title("Оригінал")
# # plt.imshow(cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB))
# # plt.axis("off")

# # plt.subplot(1, 3, 2)
# # plt.title("Низька роздільна здатність")
# # plt.imshow(low_res)
# # plt.axis("off")

# # plt.subplot(1, 3, 3)
# # plt.title("Апскейл (аналог DLSS)")
# # plt.imshow(upscaled_image)
# # plt.axis("off")

# # plt.tight_layout()
# # plt.show()

# import torch
# import torch_directml
# dml = torch_directml.device()
# print(dml)  # Should show your AMD GPU

# tensor1 = torch.tensor([1]).to(dml) # Note that dml is a variable, not a string!
# tensor2 = torch.tensor([2]).to(dml)

# dml_algebra = tensor1 + tensor2
# print(dml_algebra.item())

# import tkinter as tk
# from tkinter import ttk

# class App:
#     def __init__(self, root):
#         self.root = root
#         self.build_history_frame()

#     def build_history_frame(self):
#         """Builds the history frame with a scrollable canvas for thumbnails."""
#         # Wrapper frame for history
#         self.history_wrapper = ttk.Frame(self.root)
#         self.history_wrapper.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
#         #self.history_wrapper.grid_propagate(False)
#         #self.history_wrapper.pack_propagate(False)

#         # Scrollbar
#         self.history_scrollbar = ttk.Scrollbar(self.history_wrapper, orient='vertical')
#         self.history_scrollbar.pack(side="right", fill="y")

#         # Canvas for thumbnails
#         self.photo_frame_extra_canvas = tk.Canvas(self.history_wrapper, background="red", yscrollcommand=self.history_scrollbar.set)
#         self.photo_frame_extra_canvas.pack(side="left", fill="both", expand=True)

#         self.history_scrollbar.config(command=self.photo_frame_extra_canvas.yview)

#         # Frame inside the canvas (scrollable content)
#         self.photo_frame_extra = ttk.Frame(self.photo_frame_extra_canvas, borderwidth=3, relief="solid")
#         self.photo_frame_extra_id = self.photo_frame_extra_canvas.create_window((0, 0), window=self.photo_frame_extra, anchor="nw")

#         # Bind resizing and scrolling events
#         self.photo_frame_extra.bind("<Configure>", self.on_photo_frame_extra_resize)
#         self.photo_frame_extra.bind("<MouseWheel>", self.on_mousewheel)  # Windows/macOS
#         self.photo_frame_extra_canvas.bind("<Configure>", self.on_canvas_resize)
#         self.photo_frame_extra_canvas.bind("<Button-4>", self.on_mousewheel)  # Linux scroll up
#         self.photo_frame_extra_canvas.bind("<Button-5>", self.on_mousewheel)  # Linux scroll down

#         # Add test content (for debugging)
#         for i in range(20):  # Add 20 sample labels to ensure scrolling is needed
#             ttk.Label(self.photo_frame_extra, text=f"Item {i+1}", padding=5).pack(anchor="w", padx=10, pady=2)

#         # Force update the scroll region after adding items
#         self.update_scroll_region()

#     def update_scroll_region(self):
#         """Update the scroll region to ensure proper scrolling."""
#         self.photo_frame_extra_canvas.update_idletasks()  # Ensure layout is up to date
#         self.photo_frame_extra_canvas.config(scrollregion=self.photo_frame_extra_canvas.bbox("all"))

#     def on_mousewheel(self, event):
#         """Enable smooth scrolling with mouse wheel across different OS."""
#         if event.num == 4:  # Linux scroll up
#             self.photo_frame_extra_canvas.yview_scroll(-1, "units")
#         elif event.num == 5:  # Linux scroll down
#             self.photo_frame_extra_canvas.yview_scroll(1, "units")
#         else:  # Windows & macOS
#             self.photo_frame_extra_canvas.yview_scroll(-1 * (event.delta // 120), "units")

#     def on_photo_frame_extra_resize(self, event):
#         """Adjust the scroll region when the inner frame changes size."""
#         if self.photo_frame_extra.winfo_height() > self.photo_frame_extra_canvas.winfo_height():
#             self.history_scrollbar.pack(side="right", fill="y")
#             self.photo_frame_extra_canvas.config(yscrollcommand=self.history_scrollbar.set)
#         else:
#             self.history_scrollbar.pack_forget()
        
#         self.update_scroll_region()  # Ensures scrolling works correctly

#     def on_canvas_resize(self, event):
#         """Resize the inner frame width to match the canvas width."""
#         canvas_width = event.width
#         self.photo_frame_extra_canvas.itemconfig(self.photo_frame_extra_id, width=canvas_width)

# # Run the app
# root = tk.Tk()
# root.geometry("300x400")  # Set window size explicitly
# root.grid_rowconfigure(1, weight=1)
# root.grid_columnconfigure(0, weight=1)

# app = App(root)
# root.mainloop()

# from tkinter import *
# from PIL import ImageTk, Image

# main_window=Tk()
# main_window.title("Python Tkinter Cursors")
# bgColor="#24252B"
# fgColor ="#ffffff"
# cursors = [
# ["arrow",
#  "circle",
#  "clock",
#  "cross",
#  "dotbox"],
# ["exchange",
# "fleur",
# "heart",
# "man",
# "mouse"],
# ["pirate",
# "plus",
# "shuttle",
# "sizing",
# "spider"],
# ["spraycan",
# "star",
# "target",
# "tcross",
# "trek"],
# ["watch",
# "based_arrow_down",
# "middlebutton",
# "based_arrow_up",
# "boat"],
# ["pencil",
# "bogosity",
# "bottom_left_corner",
# "bottom_right_corner",
# "question_arrow",],
# ["bottom_side",
# "right_ptr",
# "bottom_tee",
# "box_spiral",
# "right_tee"],
# ["center_ptr",
# "rightbutton",
# "rtl_logo",
# "sailboat",
# "coffee_mug"],
# ["sb_down_arrow",
# "cross_reverse",
# "crosshair",
# "sb_h_double_arrow" ,
# "sb_left_arrow",],
# ["sb_right_arrow",
# "diamond_cross",
# "sb_up_arrow",
# "dot",
# "sb_v_double_arrow"],
# ["gumby",
# "gobbler",
# "icon",
# "double_arrow",
# "draft_large"],
# ["draft_small",
# "draped_box",
# "top_left_arrow",
# "top_left_corner",
# "hand1"],
# ["top_right_corner",
# "hand2",
# "top_side",
# "top_tee",
# "iron_cross"],
# ["ul_angle",
# "left_ptr",
# "umbrella",
# "left_side",
# "ur_angle"],
# ["left_tee",
# "leftbutton",
# "xterm",
# "ll_angle",
# "X_cursor",],
# ["lr_angle",
# "lr_angle",
# "lr_angle",
# "lr_angle",
# "lr_angle"]
# ]
    
# main_window.geometry('600x550+500+50') 
# main_window.configure(bg="#24252B")

# toAdd=0
# labels=[]
# canvas = []

# for i in range (4):
#     labels.append([])
#     canvas.append([])
#     for j in range (5):
#         lab = Label(main_window,text=cursors[i][j],
#                 bg=bgColor,fg=fgColor)
#         lab.grid(row=i*2,column=j)
#         labels[i].append(lab)
        
#         can = Canvas(main_window, width=80, height=80,
#                         cursor=cursors[i][j],
#                         bg=bgColor)
#         imageFile = Image.open("cursors/"+cursors[i][j]+".png")
#         imageFile = ImageTk.PhotoImage(imageFile)
#         can.image = imageFile
#         can.create_image(80/2, 80/2, anchor=CENTER, image=imageFile, tags="bg_img")
#         can.grid(row=i*2+1,column=j,padx=8,pady=8)
#         canvas[i].append(can)
        
# def updateCursors():
#     global labels
#     global canvas
#     for i in range (4):
#         for j in range (5):
#             labels[i][j].configure(text=cursors[i+toAdd][j])
#             canvas[i][j].configure(cursor=cursors[i+toAdd][j])
#             imageFile = Image.open("cursors/"+cursors[i+toAdd][j]+".png")
#             imageFile = ImageTk.PhotoImage(imageFile)
#             canvas[i][j].image = imageFile
#             canvas[i][j].create_image(80/2, 80/2, 
#                     anchor=CENTER, image=imageFile, tags="bg_img")

# def nextPage():
#     global toAdd
#     if toAdd<12:
#         toAdd=toAdd+4
#         updateCursors()


# def prevPage():
#     global toAdd
#     if toAdd>0:
#         toAdd=toAdd-4
#         updateCursors()     

# def firstPage():
#     global toAdd
#     toAdd=0     
#     updateCursors()   

# def lastPage():
#     global toAdd
#     toAdd=12     
#     updateCursors()           

# firstBut = Button(main_window,text="First",bg="#bd9b16",
#                  command=firstPage)
# firstBut.grid(row=8,column=0,padx=8,pady=8,sticky=E)
# lastBut = Button(main_window,text="Last",bg="#bd9b16",
#                  command=lastPage)
# lastBut.grid(row=8,column=1,padx=8,pady=8,sticky=W)


# prevBut = Button(main_window,text="Previous",bg="#bd9b16",
#                  command=prevPage)
# prevBut.grid(row=8,column=4,padx=8,pady=8,sticky=E)
# nextBut = Button(main_window,text="Next",bg="#bd9b16",
#                  command=nextPage)
# nextBut.grid(row=8,column=5,padx=8,pady=8,sticky=E)


# main_window.mainloop()

# import cv2
# import numpy as np
# from PIL import Image

# def add_gaussian_noise(image, mean=0, sigma=25):
#     noise = np.random.normal(mean, sigma, image.shape).astype(np.float32)
#     noisy_img = cv2.add(image.astype(np.float32), noise)
#     return np.clip(noisy_img, 0, 255).astype(np.uint8)

# def psnr(target, ref):
#     target_data = target.astype(np.float32)
#     ref_data = ref.astype(np.float32)
#     mse = np.mean((ref_data - target_data) ** 2)
#     if mse == 0:
#         return float('inf')
#     return 20 * np.log10(255.0 / np.sqrt(mse))

# def denoise_methods(noisy_img):
#     methods = {}

#     # 1. Gaussian Blur
#     methods['GaussianBlur'] = cv2.GaussianBlur(noisy_img, (5, 5), 0)

#     # 2. Median Blur
#     methods['MedianBlur'] = cv2.medianBlur(noisy_img, 5)

#     # 3. Bilateral Filter
#     methods['BilateralFilter'] = cv2.bilateralFilter(noisy_img, 9, 75, 75)

#     # 4. Non-Local Means
#     methods['FastNlMeans'] = cv2.fastNlMeansDenoisingColored(noisy_img, None, 10, 10, 6, 18)

#     return methods

# def evaluate_methods(original, denoised_dict):
#     scores = {}
#     for method, output in denoised_dict.items():
#         score = psnr(original, output)
#         scores[method] = score
#     return scores

# def main():
#     # Load original image
#     original = Image.open("./TEST_IMAGES/car-denoise.webp")
#     original = np.array(original)

#     # Denoise using different methods
#     denoised_results = denoise_methods(original)

#     # Evaluate and find the best one
#     psnr_scores = evaluate_methods(original, denoised_results)
#     best_method = min(psnr_scores, key=psnr_scores.get)
#     best_image = denoised_results[best_method]

#     # Output
#     print(f"Best method: {best_method} with PSNR = {psnr_scores[best_method]:.2f} dB")
#     cv2.imwrite("noisy_image.jpg", original)
#     cv2.imwrite(f"best_denoised_{best_method}.jpg", best_image)

#     # Optional: Show results
#     cv2.imshow("Original", original)
#     cv2.imshow("Noisy", original)
#     cv2.imshow("Best Denoised", best_image)
#     cv2.waitKey(0)
#     cv2.destroyAllWindows()

# if __name__ == "__main__":
#     main()

# from PIL import Image
# import matplotlib.pyplot as plt
# import torch
# import torchvision.transforms as T
# import torch.nn.functional as F

# # Load the image
# image_path = "./TEST_IMAGES/low_res_image.jpg"
# image = Image.open(image_path).convert("RGB")

# # Resize for simplicity (smaller size for visualization)
# image = image.resize((64, 64))  # downscale for easier tiling

# # Convert to tensor
# transform = T.ToTensor()
# img_tensor = transform(image).unsqueeze(0)  # shape: (1, 3, H, W)

# # Define tile size and padding
# tile_size = 32
# tile_pad = 8

# # Extract tile from top-left corner
# tile = img_tensor[:, :, 0:tile_size, 0:tile_size]

# # Apply reflect padding
# padded_tile = F.pad(tile, (tile_pad, tile_pad, tile_pad, tile_pad), mode='reflect')

# # Convert tensors back to images for visualization
# to_pil = T.ToPILImage()
# tile_img = to_pil(tile.squeeze(0))
# padded_tile_img = to_pil(padded_tile.squeeze(0))

# # Plot original tile and padded tile
# fig, axs = plt.subplots(1, 2, figsize=(10, 5))
# axs[0].imshow(tile_img)
# axs[0].set_title("Original Tile (32×32)")
# axs[0].axis("off")

# axs[1].imshow(padded_tile_img)
# axs[1].set_title("Padded Tile (Reflect, 48×48)")
# axs[1].axis("off")

# plt.tight_layout()
# plt.show()

# import numpy as np
# from PIL import Image
# import matplotlib.pyplot as plt
# import matplotlib.patches as patches


# def tile_image_with_overlap(image: Image.Image, tile_size: int, overlap: int):
#     width, height = image.size
#     stride = tile_size - overlap

#     tiles = []
#     positions = []
#     valid_sizes = []

#     for y in range(0, height, stride):
#         for x in range(0, width, stride):
#             x_end = min(x + tile_size, width)
#             y_end = min(y + tile_size, height)
#             real_w = x_end - x
#             real_h = y_end - y

#             tile = image.crop((x, y, x_end, y_end))
#             padded_tile = Image.new("RGB", (tile_size, tile_size))
#             padded_tile.paste(tile, (0, 0))

#             tiles.append(padded_tile)
#             positions.append((x, y))
#             valid_sizes.append((real_w, real_h))

#     return tiles, positions, valid_sizes, (width, height)


# def visualize_tiling(image: Image.Image, tile_size: int, overlap: int):
#     _, positions, _, _ = tile_image_with_overlap(image, tile_size, overlap)

#     fig, ax = plt.subplots(figsize=(10, 10))
#     ax.imshow(image)

#     for (x, y) in positions:
#         rect = patches.Rectangle((x, y), tile_size, tile_size, linewidth=2,
#                                  edgecolor='red', facecolor='none', alpha=0.5)
#         ax.add_patch(rect)

#     ax.set_title(f'Розбиття зображення на фрагменти з розміром {tile_size} і перекриттям {overlap}')
#     plt.axis('off')
#     plt.tight_layout()
#     plt.show()


# if __name__ == "__main__":
#     # Заміни шлях до зображення на свій файл
#     image_path = "./TEST_IMAGES/low_res_image.jpg"
#     tile_size = 128
#     overlap = 64

#     img = Image.open(image_path).convert("RGB")
#     visualize_tiling(img, tile_size, overlap)

