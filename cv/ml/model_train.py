from ultralytics import YOLO

model = YOLO('runs/detect/train/weights/1-version.pt')

model.train(
    data='data.yaml',
    epochs=32,
    lr0=0.001,
    imgsz=640,
    project='runs/detect',
    name='train',
    exist_ok=True
)