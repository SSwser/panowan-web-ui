import argparse
import cv2
import glob
import mimetypes
import numpy as np
import os
import shutil
import subprocess
from fractions import Fraction
import torch
from os import path as osp
from tqdm import tqdm

from realesrgan import RealESRGANer
from realesrgan.srvgg_arch import SRVGGNetCompact

try:
    import ffmpeg
except ImportError as exc:
    raise RuntimeError(
        "ffmpeg-python is required in the RealESRGAN backend environment"
    ) from exc

try:
    from gfpgan import GFPGANer
except ImportError:
    GFPGANer = None


def count_frames(video_path, ffmpeg_bin):
    probe = ffmpeg.probe(video_path, cmd=ffmpeg_bin)
    video_streams = [
        stream for stream in probe["streams"] if stream["codec_type"] == "video"
    ]
    if not video_streams:
        raise RuntimeError(f"No video stream found in {video_path}")
    frame_total = video_streams[0].get("nb_frames")
    if not frame_total:
        frame_total = probe.get("format", {}).get("nb_streams")
    if not frame_total:
        raise RuntimeError(
            f"Unable to determine nb_frames for {video_path}; ffprobe metadata is incomplete"
        )
    return int(frame_total)


def get_video_meta_info(video_path, ffmpeg_bin):
    ret = {}
    probe = ffmpeg.probe(video_path, cmd=ffmpeg_bin)
    video_streams = [
        stream for stream in probe["streams"] if stream["codec_type"] == "video"
    ]
    if not video_streams:
        raise RuntimeError(f"No video stream found in {video_path}")
    has_audio = any(stream["codec_type"] == "audio" for stream in probe["streams"])
    avg_frame_rate = video_streams[0].get("avg_frame_rate")
    if not avg_frame_rate or avg_frame_rate == "0/0":
        raise RuntimeError(
            f"Unable to determine avg_frame_rate for {video_path}; ffprobe metadata is incomplete"
        )
    ret["width"] = video_streams[0]["width"]
    ret["height"] = video_streams[0]["height"]
    ret["fps"] = float(Fraction(avg_frame_rate))
    ret["audio"] = ffmpeg.input(video_path).audio if has_audio else None
    ret["nb_frames"] = video_streams[0].get("nb_frames")
    if not ret["nb_frames"]:
        ret["nb_frames"] = count_frames(video_path, ffmpeg_bin)
    else:
        ret["nb_frames"] = int(ret["nb_frames"])
    return ret


def get_sub_video(args, num_process, process_idx):
    if num_process == 1:
        return args.input
    meta = get_video_meta_info(args.input, args.ffmpeg_bin)
    duration = int(meta["nb_frames"] / meta["fps"])
    part_time = duration // num_process
    print(f"duration: {duration}, part_time: {part_time}")
    os.makedirs(
        osp.join(args.output, f"{args.video_name}_inp_tmp_videos"), exist_ok=True
    )
    out_path = osp.join(
        args.output, f"{args.video_name}_inp_tmp_videos", f"{process_idx:03d}.mp4"
    )
    cmd = [
        args.ffmpeg_bin,
        f"-i {args.input}",
        "-ss",
        f"{part_time * process_idx}",
        (
            f"-to {part_time * (process_idx + 1)}"
            if process_idx != num_process - 1
            else ""
        ),
        "-async 1",
        out_path,
        "-y",
    ]
    print(" ".join(cmd))
    subprocess.call(" ".join(cmd), shell=True)
    return out_path


class Reader:

    def __init__(self, args, total_workers=1, worker_idx=0):
        self.args = args
        input_type = mimetypes.guess_type(args.input)[0]
        self.input_type = "folder" if input_type is None else input_type
        self.paths = []  # for image&folder type
        self.audio = None
        self.input_fps = None
        if self.input_type.startswith("video"):
            video_path = get_sub_video(args, total_workers, worker_idx)
            self.stream_reader = (
                ffmpeg.input(video_path)
                .output("pipe:", format="rawvideo", pix_fmt="bgr24", loglevel="error")
                .run_async(pipe_stdin=True, pipe_stdout=True, cmd=args.ffmpeg_bin)
            )
            meta = get_video_meta_info(video_path, args.ffmpeg_bin)
            self.width = meta["width"]
            self.height = meta["height"]
            self.input_fps = meta["fps"]
            self.audio = meta["audio"]
            self.nb_frames = meta["nb_frames"]

        else:
            if self.input_type.startswith("image"):
                self.paths = [args.input]
            else:
                paths = sorted(glob.glob(os.path.join(args.input, "*")))
                tot_frames = len(paths)
                num_frame_per_worker = tot_frames // total_workers + (
                    1 if tot_frames % total_workers else 0
                )
                self.paths = paths[
                    num_frame_per_worker
                    * worker_idx : num_frame_per_worker
                    * (worker_idx + 1)
                ]

            self.nb_frames = len(self.paths)
            assert self.nb_frames > 0, "empty folder"
            from PIL import Image

            tmp_img = Image.open(self.paths[0])
            self.width, self.height = tmp_img.size
        self.idx = 0

    def get_resolution(self):
        return self.height, self.width

    def get_fps(self):
        if self.args.fps is not None:
            return self.args.fps
        elif self.input_fps is not None:
            return self.input_fps
        return 24

    def get_audio(self):
        return self.audio

    def __len__(self):
        return self.nb_frames

    def get_frame_from_stream(self):
        img_bytes = self.stream_reader.stdout.read(
            self.width * self.height * 3
        )  # 3 bytes for one pixel
        if not img_bytes:
            return None
        img = np.frombuffer(img_bytes, np.uint8).reshape([self.height, self.width, 3])
        return img

    def get_frame_from_list(self):
        if self.idx >= self.nb_frames:
            return None
        img = cv2.imread(self.paths[self.idx])
        self.idx += 1
        return img

    def get_frame(self):
        if self.input_type.startswith("video"):
            return self.get_frame_from_stream()
        else:
            return self.get_frame_from_list()

    def close(self):
        if self.input_type.startswith("video"):
            self.stream_reader.stdin.close()
            self.stream_reader.wait()


class Writer:

    def __init__(self, args, audio, height, width, video_save_path, fps):
        out_width, out_height = int(width * args.outscale), int(height * args.outscale)
        if out_height > 2160:
            print(
                "You are generating video that is larger than 4K, which will be very slow due to IO speed.",
                "We highly recommend to decrease the outscale(aka, -s).",
            )

        if audio is not None:
            self.stream_writer = (
                ffmpeg.input(
                    "pipe:",
                    format="rawvideo",
                    pix_fmt="bgr24",
                    s=f"{out_width}x{out_height}",
                    framerate=fps,
                )
                .output(
                    audio,
                    video_save_path,
                    pix_fmt="yuv420p",
                    vcodec="libx264",
                    loglevel="error",
                    acodec="copy",
                )
                .overwrite_output()
                .run_async(pipe_stdin=True, pipe_stdout=True, cmd=args.ffmpeg_bin)
            )
        else:
            self.stream_writer = (
                ffmpeg.input(
                    "pipe:",
                    format="rawvideo",
                    pix_fmt="bgr24",
                    s=f"{out_width}x{out_height}",
                    framerate=fps,
                )
                .output(
                    video_save_path,
                    pix_fmt="yuv420p",
                    vcodec="libx264",
                    loglevel="error",
                )
                .overwrite_output()
                .run_async(pipe_stdin=True, pipe_stdout=True, cmd=args.ffmpeg_bin)
            )

    def write_frame(self, frame):
        frame = frame.astype(np.uint8).tobytes()
        self.stream_writer.stdin.write(frame)

    def close(self):
        self.stream_writer.stdin.close()
        self.stream_writer.wait()


def inference_video(args, video_save_path, device=None, total_workers=1, worker_idx=0):
    # Vendored runtime keeps only the anime-video inference path used by the worker.
    args.model_name = args.model_name.split(".pth")[0]
    if args.model_name != "realesr-animevideov3":
        raise ValueError(
            "Vendored RealESRGAN runtime only supports realesr-animevideov3"
        )

    model = SRVGGNetCompact(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=64,
        num_conv=16,
        upscale=4,
        act_type="prelu",
    )
    netscale = 4

    if args.model_path is None:
        raise RuntimeError(
            "Vendored RealESRGAN runtime requires --model_path for the checkpoint"
        )

    model_path = args.model_path

    # restorer
    upsampler = RealESRGANer(
        scale=netscale,
        model_path=model_path,
        model=model,
        tile=args.tile,
        tile_pad=args.tile_pad,
        pre_pad=args.pre_pad,
        half=not args.fp32,
        device=device,
    )

    if args.face_enhance:
        raise RuntimeError(
            "face_enhance is unsupported in generated runtime bundle; only core anime-video upscaling is supported"
        )

    face_enhancer = None

    if GFPGANer is not None:
        _ = GFPGANer

    reader = Reader(args, total_workers, worker_idx)
    audio = reader.get_audio()
    height, width = reader.get_resolution()
    fps = reader.get_fps()
    writer = Writer(args, audio, height, width, video_save_path, fps)

    pbar = tqdm(total=len(reader), unit="frame", desc="inference")
    while True:
        img = reader.get_frame()
        if img is None:
            break

        try:
            output, _ = upsampler.enhance(img, outscale=args.outscale)
        except RuntimeError as error:
            raise RuntimeError(
                f"RealESRGAN inference failed on frame {pbar.n + 1}: {error}. "
                "If you encounter CUDA out of memory, try to set --tile with a smaller number."
            ) from error

        writer.write_frame(output)

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        pbar.update(1)

    reader.close()
    writer.close()


def run(args):
    args.video_name = osp.splitext(os.path.basename(args.input))[0]
    video_save_path = osp.join(args.output, f"{args.video_name}_{args.suffix}.mp4")

    if args.extract_frame_first:
        tmp_frames_folder = osp.join(args.output, f"{args.video_name}_inp_tmp_frames")
        os.makedirs(tmp_frames_folder, exist_ok=True)
        os.system(
            f"ffmpeg -i {args.input} -qscale:v 1 -qmin 1 -qmax 1 -vsync 0  {tmp_frames_folder}/frame%08d.png"
        )
        args.input = tmp_frames_folder

    num_gpus = torch.cuda.device_count()
    num_process = num_gpus * args.num_process_per_gpu
    if num_process == 1:
        inference_video(args, video_save_path)
        return

    ctx = torch.multiprocessing.get_context("spawn")
    pool = ctx.Pool(num_process)
    os.makedirs(
        osp.join(args.output, f"{args.video_name}_out_tmp_videos"), exist_ok=True
    )
    pbar = tqdm(total=num_process, unit="sub_video", desc="inference")
    for i in range(num_process):
        sub_video_save_path = osp.join(
            args.output, f"{args.video_name}_out_tmp_videos", f"{i:03d}.mp4"
        )
        pool.apply_async(
            inference_video,
            args=(
                args,
                sub_video_save_path,
                torch.device(i % num_gpus),
                num_process,
                i,
            ),
            callback=lambda arg: pbar.update(1),
        )
    pool.close()
    pool.join()

    # combine sub videos
    # prepare vidlist.txt
    with open(f"{args.output}/{args.video_name}_vidlist.txt", "w") as f:
        for i in range(num_process):
            f.write(f"file '{args.video_name}_out_tmp_videos/{i:03d}.mp4'\n")

    cmd = [
        args.ffmpeg_bin,
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        f"{args.output}/{args.video_name}_vidlist.txt",
        "-c",
        "copy",
        f"{video_save_path}",
    ]
    print(" ".join(cmd))
    subprocess.call(cmd)
    shutil.rmtree(osp.join(args.output, f"{args.video_name}_out_tmp_videos"))
    if osp.exists(osp.join(args.output, f"{args.video_name}_inp_tmp_videos")):
        shutil.rmtree(osp.join(args.output, f"{args.video_name}_inp_tmp_videos"))
    os.remove(f"{args.output}/{args.video_name}_vidlist.txt")


def main():
    """Inference demo for Real-ESRGAN.
    It mainly for restoring anime videos.

    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i", "--input", type=str, default="inputs", help="Input video, image or folder"
    )
    parser.add_argument(
        "-n",
        "--model_name",
        type=str,
        default="realesr-animevideov3",
        help="Supported model name. Only realesr-animevideov3 is available.",
    )
    parser.add_argument(
        "-o", "--output", type=str, default="results", help="Output folder"
    )
    parser.add_argument(
        "-s",
        "--outscale",
        type=float,
        default=4,
        help="The final upsampling scale of the image",
    )
    parser.add_argument(
        "--model_path",
        type=str,
        default=None,
        help="Absolute path to the model checkpoint",
    )
    parser.add_argument(
        "--suffix", type=str, default="out", help="Suffix of the restored video"
    )
    parser.add_argument(
        "-t",
        "--tile",
        type=int,
        default=0,
        help="Tile size, 0 for no tile during testing",
    )
    parser.add_argument("--tile_pad", type=int, default=10, help="Tile padding")
    parser.add_argument(
        "--pre_pad", type=int, default=0, help="Pre padding size at each border"
    )
    parser.add_argument(
        "--face_enhance", action="store_true", help="Use GFPGAN to enhance face"
    )
    parser.add_argument(
        "--fp32",
        action="store_true",
        help="Use fp32 precision during inference. Default: fp16 (half precision).",
    )
    parser.add_argument(
        "--fps", type=float, default=None, help="FPS of the output video"
    )
    parser.add_argument(
        "--ffmpeg_bin", type=str, default="ffmpeg", help="The path to ffmpeg"
    )
    parser.add_argument("--extract_frame_first", action="store_true")
    parser.add_argument("--num_process_per_gpu", type=int, default=1)

    args = parser.parse_args()

    args.input = args.input.rstrip("/").rstrip("\\")
    os.makedirs(args.output, exist_ok=True)

    if mimetypes.guess_type(args.input)[0] is not None and mimetypes.guess_type(
        args.input
    )[0].startswith("video"):
        is_video = True
    else:
        is_video = False

    if is_video and args.input.endswith(".flv"):
        mp4_path = args.input.replace(".flv", ".mp4")
        os.system(f"ffmpeg -i {args.input} -codec copy {mp4_path}")
        args.input = mp4_path

    if args.extract_frame_first and not is_video:
        args.extract_frame_first = False

    run(args)

    if args.extract_frame_first:
        tmp_frames_folder = osp.join(args.output, f"{args.video_name}_inp_tmp_frames")
        shutil.rmtree(tmp_frames_folder)


if __name__ == "__main__":
    main()
