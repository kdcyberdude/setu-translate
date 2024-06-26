import os
import torch
from IndicTransTokenizer import IndicProcessor, IndicTransTokenizer
from datasets import load_dataset

import glob
from functools import partial

import json

import argparse

def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

def parse_args():

    parser = argparse.ArgumentParser(description="Perform decoding")

    parser.add_argument(
        "--data_files",
        type=str,
    )

    parser.add_argument(
        "--format",
        type=str,
        default="arrow",
        required=False
    )

    parser.add_argument(
        "--cache_dir",
        type=str,
    )

    parser.add_argument(
        "--decode_dir",
        type=str,
    )

    parser.add_argument(
        "--batch_size",
        type=int,
    )

    parser.add_argument(
        "--total_procs",
        type=int
    )

    parser.add_argument(
        "--save_strs",
        type=str2bool,
        required=False,
        default=True
    )

    parser.add_argument(
        "--src_lang",
        type=str,
    )

    parser.add_argument(
        "--tgt_lang",
        type=str,
    )

    args = parser.parse_args()

    return args

def decode(
    batch,
    src_lang="eng_Latn",
    tgt_lang="hin_Deva"
):
    
    ip = IndicProcessor(inference=True)
    tokenizer = IndicTransTokenizer(direction="en-indic")

    p_batch = dict()
    input_ids = batch.pop("translated_input_ids")
    placeholder_entity_maps = list(map(lambda ple_map: json.loads(ple_map), batch["placeholder_entity_map"]))
    outputs = tokenizer.batch_decode(input_ids, src=False)
    p_batch["translated"] = ip.postprocess_batch(outputs, lang=tgt_lang, placeholder_entity_maps=placeholder_entity_maps)
    return p_batch | {
        "translated_input_ids": input_ids,
    }

def save_to_str_lvl(batch):
    written_file = []
    created_dirs = set()  # Keep track of already created directories

    for sid, tlt_file_loc, translated in zip(batch["sid"], batch["tlt_file_loc"], batch["translated"]):
        try:
            file_dir = os.path.dirname(tlt_file_loc)
            if file_dir not in created_dirs:
                os.makedirs(file_dir, exist_ok=True)
                created_dirs.add(file_dir)

            with open(tlt_file_loc, "w") as str_f:
                str_f.write(translated)
            written_file.append(True)
        except Exception:
            written_file.append(False)

    return batch | {"written": written_file}


if __name__ == "__main__":

    args = parse_args()

    ds = load_dataset(
        args.format,
        data_files=glob.glob(args.data_files),
        num_proc=args.total_procs,
        cache_dir=args.cache_dir,  
        split="train"
    )

    print("Loaded Dataset to decode....")

    decoded_ds = ds.map(
        partial(
            decode,
            src_lang=args.src_lang,
            tgt_lang=args.tgt_lang,
        ),
        batched=True,
        batch_size=args.batch_size,
        num_proc=args.total_procs,
    )

    if args.save_strs:
        decoded_ds = decoded_ds.map(
            save_to_str_lvl,
            batched=True,
            batch_size=args.batch_size,
            num_proc=args.total_procs,
        )

    os.makedirs(args.decode_dir, exist_ok=True)
    print('Saving Decoded Dataset....')

    decoded_ds.save_to_disk(
        args.decode_dir,
        num_proc=args.total_procs,
    )

    