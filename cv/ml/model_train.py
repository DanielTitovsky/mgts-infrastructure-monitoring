from ultralytics import YOLO

model = YOLO('yolo-v/yolov8n.pt')

model.train(
    data='dataset/data.yaml',
    epochs=50,
    lr0=0.001,
    conf=0.5,
    close_mosaic=50,
    imgsz=640,
)