import numpy as np
import torch
from datasets import load_dataset, Dataset, concatenate_datasets
from torch.utils.data import DataLoader
from functools import partial
import glob
import os
import re
import pandas as pd
import csv
from document import Document
import argparse
import json
import os
import multiprocessing as mp
from joblib import Parallel, delayed
import sys
import tqdm
import requests
import time
from datetime import datetime
import traceback

def cleanup(
    idx_logging,
    resume_log_file_path,
    run_ds,
    run_dir
):
    with open(resume_log_file_path, "a+") as resume_f:
        resume_f.write(f'Saving latest resume-index: <{idx_logging}> at - {datetime.now().strftime("%m/%d/%Y, %H:%M:%S")}\n')
    print(f"Saved `resume_idx` to {resume_log_file_path}....")

    run_ds_save_path = os.path.join(run_dir, datetime.now().strftime("%m_%d_%Y-%H:%M:%S"))
    run_ds.to_csv(
        run_ds_save_path,
        num_proc=128,
    )
    print(f"Saved latest `run_ds` to {run_ds_save_path}....")
    
    print("Performed clean-up!")

def extract_resume_idx(text):

    # Regular expression to find text between < and >
    pattern = re.compile(r'<(.*?)>')

    # Find all occurrences of the pattern
    matches = pattern.findall(text)

    return matches

def send_request(texts, src_lang, tgt_lang, server_url="http://0.0.0.0:8000/v2/models/nmt/infer", auth_key=None):

    # The inference server URL
    TRITON_SERVER_URL = server_url

    # Authentication header
    headers = {
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json"
    }

    body = json.dumps({
        "inputs": [
            {
                "name": "INPUT_TEXT",
                "shape": [len(texts), 1],
                "datatype": "BYTES",
                "data": np.array([[text] for text in texts], dtype=object).tolist()
            },
            {
                "name": "INPUT_LANGUAGE_ID",
                "shape": [len(texts), 1],
                "datatype": "BYTES",
                "data": [[src_lang]] * len(texts),
            },
            {
                "name": "OUTPUT_LANGUAGE_ID",
                "shape": [len(texts), 1],
                "datatype": "BYTES",
                "data": [[tgt_lang]] * len(texts)
            }
        ],
        "outputs": [
            {
                "name": "OUTPUT_TEXT"
            }
        ]
    })

    # Make the request
    response = requests.post(TRITON_SERVER_URL, headers=headers, data=body)

    # Check if the request was successful
    if response.status_code != 200:
        error = f"Error during inference request: {response.text}"
        return None, error, "triton"

    # Extract results from the response
    try:
        output_data = json.loads(response.text)
    except Exception as e:
        exception_info = str(e) # Capture the exception information
        traceback_info = traceback.format_exc() # Capture the traceback
        error = f"Exception: {exception_info}\nTraceback:\n{traceback_info}" # Combine exception information and traceback
        return None, error, "response_json"

    translated_txt = output_data['outputs'][0]['data']
    return translated_txt, None, None

def translate(
    substrs_cum_path,
    src_lang, 
    tgt_lang, 
    server_url="http://0.0.0.0:8000/v2/models/nmt/infer", 
    auth_key=None
):
    substrs, path = substrs_cum_path
    try:
        translated, error, stage = send_request(json.loads(substrs), src_lang, tgt_lang, server_url, auth_key)
        if error:
            with open(f"{path}.error.{stage}", "w") as error_f:
                error_f.write(error)
            return None, False, stage
        else:
            return translated, True, None
    except Exception as e:
        exception_info = str(e) # Capture the exception information
        traceback_info = traceback.format_exc() # Capture the traceback
        error = f"Exception: {exception_info}\nTraceback:\n{traceback_info}" # Combine exception information and traceback
        with open(f"{path}.error.main", "w") as error_f:
            error_f.write(error)
        return None, False, "main"

if __name__ == "__main__":

    try:
        print("Program is running. Press Ctrl+C to interrupt.")

        root_dir = "/data-3/priyam/translation/output"

        resume_idx=None
        resume_log_file_path=f"{root_dir}/wiki_en/resume_idx_sent_lvl_log"
        run_dir=f"{root_dir}/wiki_en/run_sent_lvl"
        filetype="csv"
        data_file=f"{root_dir}/wiki_en/template_wiki_en.csv"
        cache_dir="/data-3/priyam/translation/data/wiki_en/cache"
        joblib_temp_folder=f"{root_dir}/tmp"

        if os.path.isfile(resume_log_file_path):
            with open(resume_log_file_path, "r") as resume_f:
                latest_idx = extract_resume_idx(list(map(lambda x: x.strip(), resume_f.readlines()))[-1])[0]
                resume_idx = int(latest_idx) if latest_idx and len(latest_idx) else None

        split = "train" if not resume_idx else f"train[{resume_idx}:]"

        ds = load_dataset(
            filetype,
            data_files=glob.glob(data_file),
            cache_dir=cache_dir,
            num_proc=128,
            split=split
        )
        print(f"Loaded Dataset from {data_file} and resume-idx `{resume_idx}`")

        data_loader = DataLoader(
            ds,
            num_workers=1, 
            batch_size=1024,
            prefetch_factor=8,
            shuffle=False
        )
        print(f"Created DataLoader for the dataset")

        tlt_func = partial(
            translate,
            src_lang="en",
            tgt_lang="hi", 
            server_url="http://0.0.0.0:8000/v2/models/nmt/infer", 
            auth_key=None,
        )

        idx_logging = resume_idx if resume_idx else 0
        original_columns = ['source', 'url', 'timestamp', 'doc_id', 'text', 'sub_strs', 'sids', 'csv_path']
        run_ds = Dataset.from_dict(
            { key: [] for key in original_columns + [ 'translated', 'completed', 'reason' ] },
        )
        for idx, batch in tqdm.tqdm(enumerate(data_loader, 0), unit=f"ba: {1024} samples/ba", total=len(data_loader)):
            batch_status = Parallel(
                n_jobs=512,
                verbose=0, 
                prefer="threads",
                batch_size="auto",
                pre_dispatch='2*n_jobs',
                temp_folder=joblib_temp_folder,
            )(
                delayed(tlt_func)(substr) for substr in list(zip(batch["sub_strs"], batch["csv_path"]))
            )

            idx_logging += len(batch["doc_id"])

            batch_info_mapping = { key: batch[key] for key in original_columns }
            batch_info_mapping["translated"] = [json.dumps(translated) for translated, _, _ in batch_status]
            batch_info_mapping["completed"] = [completed for _, completed, _ in batch_status]
            batch_info_mapping["reason"] = [reason for _, _, reason in batch_status]
            run_ds = concatenate_datasets(
                [
                    run_ds, 
                    Dataset.from_dict(batch_info_mapping),
                ]
            )

    except KeyboardInterrupt:

        print("Interrupted by user")

        cleanup(
            idx_logging=idx_logging,
            resume_log_file_path=resume_log_file_path,
            run_ds=run_ds,
            run_dir=run_dir,
        )

        sys.exit(0)
    