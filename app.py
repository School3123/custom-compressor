import streamlit as st
import lzma
import tarfile
import struct
import os
import shutil
import glob
import io
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ 設定・定数
# ==========================================
MAGIC_NUMBER = b'MYCP_ULT' # Ultimate Version
VERSION_LABEL = "V13 (Ultimate Edition)"

# ディレクトリ構成
DIR_INPUT_RAW = "workspace/input_raw"
DIR_OUTPUT_ARCHIVE = "workspace/output_archives"
DIR_INPUT_COMPRESSED = "workspace/input_compressed"
DIR_EXTRACTED = "workspace/extracted_output"
ALL_DIRS = [DIR_INPUT_RAW, DIR_OUTPUT_ARCHIVE, DIR_INPUT_COMPRESSED, DIR_EXTRACTED]

# ==========================================
# 🛠️ ユーティリティ関数
# ==========================================
def init_directories():
    """必要なディレクトリ構造を初期化"""
    for d in ALL_DIRS:
        os.makedirs(d, exist_ok=True)

def clear_workspace():
    """ワークスペースの全ファイルとセッション状態を削除"""
    if 'scan_result' in st.session_state:
        del st.session_state['scan_result']
    for d in ALL_DIRS:
        if os.path.exists(d): shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

def clear_extracted_folder():
    """解凍先フォルダのみクリア"""
    if os.path.exists(DIR_EXTRACTED):
        shutil.rmtree(DIR_EXTRACTED)
    os.makedirs(DIR_EXTRACTED, exist_ok=True)

class ProgressFileObject:
    """バイト単位の進捗状況をコールバックするファイルラッパー"""
    def __init__(self, path, callback):
        self._f = open(path, "rb")
        self._callback = callback
        self._f.seek(0, os.SEEK_END)
        self._len = self._f.tell()
        self._f.seek(0)

    def read(self, size=-1):
        data = self._f.read(size)
        if data:
            self._callback(len(data))
        return data

    def close(self):
        self._f.close()

def reset_tar_info(tarinfo):
    """メタデータ（所有者・日時）を削除し、圧縮効率を高める（ノイズ除去）"""
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = "root"
    tarinfo.gname = "root"
    tarinfo.mtime = 0 # 1970/1/1 固定
    return tarinfo

def process_file_metadata(args):
    """並列処理用: ファイルのハッシュ・ヘッダー・サイズを取得"""
    fname, input_dir = args
    fpath = os.path.join(input_dir, fname)
    if not os.path.exists(fpath): return None

    size = os.path.getsize(fpath)
    sha256 = hashlib.sha256()
    header = b''
    
    with open(fpath, "rb") as f:
        header = f.read(16) # ソート用に先頭16バイト取得
        sha256.update(header)
        while chunk := f.read(1024 * 1024): # 1MBチャンク
            sha256.update(chunk)
            
    return {
        "name": fname,
        "path": fpath,
        "size": size,
        "ext": os.path.splitext(fname)[1],
        "hash": sha256.hexdigest(),
        "header": header
    }

# ==========================================
# 🚀 圧縮ロジック (Ultimate Logic)
# ==========================================
def compress_ultimate(selected_file_names, output_filename="archive"):
    output_path = os.path.join(DIR_OUTPUT_ARCHIVE, f"{output_filename}.mycmp")
    status_area = st.empty()
    status_area.info("Status: Initializing Compression Engine...")
    
    try:
        # 1. 並列解析フェーズ (高速化)
        args_list = [(f, DIR_INPUT_RAW) for f in selected_file_names]
        file_meta = []
        total_bytes_all = 0
        
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(process_file_metadata, args_list))
            for i, res in enumerate(results):
                if res: 
                    file_meta.append(res)
                    total_bytes_all += res['size']
                if i % 5 == 0:
                    pct = int(((i+1)/len(args_list))*100)
                    status_area.text(f"Status: Analyzing Metadata... {pct}%")
        
        # 2. スマートソート (類似データを隣接させ圧縮率向上)
        # 優先順位: ヘッダーバイナリ > 拡張子 > サイズ
        sorted_files = sorted(file_meta, key=lambda x: (x['header'], x['ext'], x['size']))

        # 3. 圧縮フィルター設定 (安定・最強設定)
        # メモリ不足回避のため辞書は256MBとし、不安定なBCJフィルターは除外
        my_filters = [{
            "id": lzma.FILTER_LZMA2, 
            "preset": 6, 
            "dict_size": 256 * 1024 * 1024, # 256MB Dictionary
            "lc": 4, "lp": 0, "pb": 2, 
            "nice_len": 273, "mf": lzma.MF_BT4
        }]
        
        # 4. 書き込み実行 (重複排除 + バイト進捗)
        processed_bytes = 0
        last_update_time = 0
        
        def progress_callback(inc_bytes):
            nonlocal processed_bytes, last_update_time
            processed_bytes += inc_bytes
            current_time = time.time()
            # 0.1秒間隔でUI更新
            if current_time - last_update_time > 0.1:
                if total_bytes_all > 0:
                    pct = (processed_bytes / total_bytes_all) * 100
                    status_area.text(f"Progress: {pct:.1f}% ({processed_bytes:,} / {total_bytes_all:,} bytes)")
                last_update_time = current_time

        status_area.text("Status: Starting Compression Stream...")
        time.sleep(0.1)

        with open(output_path, "wb") as f_out:
            f_out.write(MAGIC_NUMBER)
            
            with lzma.open(f_out, "w", format=lzma.FORMAT_XZ, filters=my_filters) as lzma_file:
                with tarfile.open(fileobj=lzma_file, mode="w") as tar:
                    seen_hashes = {}
                    
                    for item in sorted_files:
                        if item['hash'] in seen_hashes:
                            # 重複排除: ハードリンク作成 (容量消費ゼロ)
                            ti = tarfile.TarInfo(item['name'])
                            ti.type = tarfile.LNKTYPE
                            ti.linkname = seen_hashes[item['hash']]
                            ti = reset_tar_info(ti)
                            tar.addfile(ti)
                        else:
                            # 実データ書き込み
                            seen_hashes[item['hash']] = item['name']
                            ti = tarfile.TarInfo(name=item['name'])
                            ti.size = item['size']
                            ti = reset_tar_info(ti) # メタデータ削除
                            
                            fileobj = ProgressFileObject(item['path'], progress_callback)
                            try:
                                tar.addfile(ti, fileobj=fileobj)
                            finally:
                                fileobj.close()

        status_area.text("Status: 100.0% - Finished!")
        time.sleep(0.5)
        return output_path

    except Exception as e:
        status_area.error(f"Critical Error: {e}")
        return None

# ==========================================
# 🔓 解凍・スキャンロジック
# ==========================================
def list_archive_contents(file_path):
    """アーカイブを解凍せずに中身のリストを取得"""
    try:
        with open(file_path, "rb") as f:
            magic = f.read(len(MAGIC_NUMBER))
            # 過去バージョンの互換性チェック（前方一致）
            if not magic.startswith(b'MYCP'):
                return None, "Invalid File Format"
            compressed_body = f.read()

        with io.BytesIO(compressed_body) as f_in:
            with lzma.open(f_in, "r", format=lzma.FORMAT_XZ) as lzma_file:
                with tarfile.open(fileobj=lzma_file, mode="r") as tar:
                    return tar.getnames(), "Success"
    except Exception as e:
        return None, str(e)

def extract_selected_files(file_path, targets):
    """選択されたファイルのみを解凍"""
    try:
        clear_extracted_folder()
        
        with open(file_path, "rb") as f:
            # ヘッダー長分スキップ（バージョンによって長さが違う可能性があるため簡易的に処理）
            # ここでは現在のMAGIC_NUMBER長で判定
            f.seek(len(MAGIC_NUMBER)) 
            compressed_body = f.read()

        with io.BytesIO(compressed_body) as f_in:
            with lzma.open(f_in, "r", format=lzma.FORMAT_XZ) as lzma_file:
                with tarfile.open(fileobj=lzma_file, mode="r") as tar:
                    # 解凍対象フィルター
                    members = [m for m in tar.getmembers() if m.name in targets]
                    if not members:
                        return False, "No matching files found."
                    
                    tar.extractall(path=DIR_EXTRACTED, members=members)
        return True, f"Extracted {len(members)} files."

    except Exception as e:
        return False, f"Extraction Error: {e}"

# ==========================================
# 🖥️ UI (Streamlit)
# ==========================================
st.set_page_config(page_title="Ultra Compressor V13", layout="wide")
init_directories()

st.title(f"🗜️ Ultra Compressor {VERSION_LABEL}")
st.markdown("""
<style>
div.stButton > button {width: 100%; border-radius: 6px; font-weight: bold;}
</style>
""", unsafe_allow_html=True)
st.caption("Features: 256MB Dict | Deduplication | Metadata Stripping | Smart Sort | Selective Extract")

# サイドバー
with st.sidebar:
    st.header("Workspace")
    if st.button("🗑️ Clear All Data", type="primary"):
        clear_workspace()
        st.rerun()
    
    st.divider()
    st.info(f"Input Raw: {len(os.listdir(DIR_INPUT_RAW))}")
    st.info(f"Archives: {len(os.listdir(DIR_OUTPUT_ARCHIVE))}")
    st.info(f"Input Comp: {len(os.listdir(DIR_INPUT_COMPRESSED))}")
    st.info(f"Extracted: {len(os.listdir(DIR_EXTRACTED))}")

tab_compress, tab_decompress = st.tabs(["📤 Compress (圧縮)", "📥 Decompress (選択解凍)"])

# === 圧縮タブ ===
with tab_compress:
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("1. Add Files")
        uploaded = st.file_uploader("Upload raw files", accept_multiple_files=True, key="up_c")
        if uploaded:
            for u in uploaded:
                with open(os.path.join(DIR_INPUT_RAW, u.name), "wb") as f:
                    f.write(u.getbuffer())
        
        files = sorted(os.listdir(DIR_INPUT_RAW))
        if files:
            st.write("---")
            selected = st.multiselect("Select files", files, default=files, key="sel_c")
        else:
            selected = []
            st.info("No files uploaded.")

    with c2:
        st.subheader("2. Settings & Run")
        out_name = st.text_input("Filename", "archive_v13", key="name_c")
        
        if st.button("🚀 Start Compression", disabled=not selected, key="btn_c"):
            start_time = time.time()
            result_path = compress_ultimate(selected, out_name)
            
            if result_path:
                elapsed = time.time() - start_time
                orig_sz = sum(os.path.getsize(os.path.join(DIR_INPUT_RAW, f)) for f in selected)
                comp_sz = os.path.getsize(result_path)
                red_pct = (1 - (comp_sz / orig_sz)) * 100 if orig_sz > 0 else 0
                
                st.balloons()
                st.success(f"Completed in {elapsed:.2f} seconds!")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Original", f"{orig_sz:,} B")
                m2.metric("Compressed", f"{comp_sz:,} B")
                m3.metric("Reduction", f"{red_pct:.2f}%")
                
                with open(result_path, "rb") as f:
                    st.download_button("⬇️ Download (.mycmp)", f, file_name=os.path.basename(result_path), key="dl_c")
                
                if st.button("🔄 Copy to Decompress Tab", key="cp_c"):
                    shutil.copy2(result_path, os.path.join(DIR_INPUT_COMPRESSED, os.path.basename(result_path)))
                    st.toast("Copied successfully!", icon="✅")
                    time.sleep(1)
                    st.rerun()

# === 解凍タブ (選択解凍) ===
with tab_decompress:
    d1, d2 = st.columns([1, 1])
    
    with d1:
        st.subheader("1. Load & Scan")
        up_arc = st.file_uploader("Upload .mycmp file", accept_multiple_files=True, type=None, key="up_d")
        if up_arc:
            for u in up_arc:
                with open(os.path.join(DIR_INPUT_COMPRESSED, u.name), "wb") as f:
                    f.write(u.getbuffer())
        
        archives = sorted(os.listdir(DIR_INPUT_COMPRESSED))
        target_arc = st.selectbox("Select Archive", archives, key="sel_d") if archives else None

        # スキャンボタン
        scan_btn = st.button("🔍 Scan Contents", disabled=target_arc is None, key="btn_scan")
        
        if scan_btn and target_arc:
            with st.spinner("Scanning archive structure..."):
                contents, msg = list_archive_contents(os.path.join(DIR_INPUT_COMPRESSED, target_arc))
                if contents is not None:
                    st.session_state['scan_result'] = {'archive': target_arc, 'files': contents}
                    st.success(f"Found {len(contents)} files.")
                else:
                    st.error(f"Scan Failed: {msg}")

    with d2:
        st.subheader("2. Select & Extract")
        
        # スキャン結果があればリスト表示
        if 'scan_result' in st.session_state and st.session_state['scan_result']['archive'] == target_arc:
            file_list = st.session_state['scan_result']['files']
            
            # マルチセレクト (デフォルト全選択)
            selected_extract = st.multiselect("Choose files to extract:", file_list, default=file_list, key="sel_ext")
            
            if st.button("🔓 Extract Selected", disabled=not selected_extract, key="btn_ext"):
                target_path = os.path.join(DIR_INPUT_COMPRESSED, target_arc)
                with st.spinner("Extracting..."):
                    success, msg = extract_selected_files(target_path, selected_extract)
                
                if success:
                    st.success(f"✅ {msg}")
                    
                    extracted_files = []
                    for root, dirs, files in os.walk(DIR_EXTRACTED):
                        for file in files:
                            extracted_files.append(os.path.join(root, file))
                    
                    if extracted_files:
                        st.write(f"**Extracted Output ({len(extracted_files)}):**")
                        with st.container(height=300):
                            for path in extracted_files:
                                rel_path = os.path.relpath(path, DIR_EXTRACTED)
                                col_name, col_dl = st.columns([3, 1])
                                col_name.text(rel_path)
                                with open(path, "rb") as f:
                                    col_dl.download_button("⬇️", f, file_name=os.path.basename(path), key=f"dl_{rel_path}")
                else:
                    st.error(f"❌ {msg}")
        
        elif target_arc:
            st.info("👈 Please scan the archive first.")
