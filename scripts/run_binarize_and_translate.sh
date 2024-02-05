#!/usr/bin/bash


shards_root_dir="output/wiki_en/shards/shards_1627"

data_cache_dir="data/wiki_en/cache"
joblib_temp_folder="tmp"
src_lang="eng_Latn"
tgt_lang="hin_Deva"
num_procs_for_data_ops=64
batch_size=512
devices_for_translation="0,1,2,3,4,5,6,7"

run_translation() {

    i=$1

    HF_DATASETS_CACHE=tmp python setu-translate/stages/binarize.py \
        --root_dir "$PWD" \
        --data_files "output/wiki_en/shards/${i}/sentences/*.arrow" \
        --cache_dir $data_cache_dir \
        --binarized_dir "output/wiki_en/shards/${i}/${tgt_lang}/binarized_sentences" \
        --joblib_temp_folder $joblib_temp_folder \
        --batch_size $batch_size \
        --total_procs $num_procs_for_data_ops \
        --run_joblib False \
        --src_lang $src_lang \
        --tgt_lang $tgt_lang

    HF_DATASETS_CACHE=tmp python setu-translate/stages/tlt_pipelines/translate_joblib.py \
        --root_dir "$PWD" \
        --data_files "output/wiki_en/shards/${i}/${tgt_lang}/binarized_sentences/*.arrow" \
        --cache_dir $data_cache_dir \
        --base_save_dir "output/wiki_en/shards/${i}/${tgt_lang}/model_out" \
        --joblib_temp_folder $joblib_temp_folder \
        --batch_size $batch_size \
        --total_procs $num_procs_for_data_ops \
        --devices $devices_for_translation

}

for (( i=$shard_size; i<=$max_limit; i+=$shard_size ))
do

    echo "Translating shard-${i}....."
    
    run_translation $i

done