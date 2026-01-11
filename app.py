import streamlit as st
import lzma
import tarfile
import struct
import os
import shutil
import glob
import io

# --- 設定 ---
MAGIC_NUMBER = b'MYCP_V3' # バージョン3 (XZフォーマット)
# 処理用ディレクトリ
DIR_INPUT = "workspace/input_files"
DIR_COMPRESSED = "workspace/compressed_output"
DIR_EXTRACTED = "workspace/extracted_output"

# ディレクトリ初期化関数
def init_directories():
    for d in [DIR_INPUT, DIR_COMPRESSED, DIR_EXTRACTED]:
        os.makedirs(d, exist_ok=True)

def clear_workspace():
    """ワークスペースの全ファイルを削除"""
    for d in [DIR_INPUT, DIR_COMPRESSED, DIR_EXTRACTED]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

def get_folder_size(path):
    """フォルダ内の合計サイズを計算"""
    total = 0
    for entry in os.scandir(path):
        if entry.is_file():
            total += entry.stat().st_size
        elif entry.is_dir():
            total += get_folder_size(entry.path)
    return total

# --- 圧縮ロジック (選択ファイルのみ処理) ---
def compress_selected_files(selected_file_names, output_filename="archive"):
    """
    指定されたファイル名のリストのみを圧縮する
    """
    output_path = os.path.join(DIR_COMPRESSED, f"{output_filename}.mycmp")
    
    try:
        # LZMA2 カスタムフィルタ (極限設定 128MB辞書)
        my_filters = [
            {
                "id": lzma.FILTER_LZMA2, 
                "preset": 9 | lzma.PRESET_EXTREME,
                "dict_size": 128 * 1024 * 1024,
                "lc": 4, 
                "lp": 0,
                "pb": 2, 
                "nice_len": 273,
                "mf": lzma.MF_BT4
            }
        ]

        with open(output_path, "wb") as f_out:
            # ヘッダー書き込み
            f_out.write(MAGIC_NUMBER)
            
            # LZMA圧縮 (FORMAT_XZ)
            with lzma.open(f_out, "w", format=lzma.FORMAT_XZ, filters=my_filters) as lzma_file:
                with tarfile.open(fileobj=lzma_file, mode="w") as tar:
                    # 選択されたファイルだけをループ処理
                    for file_name in selected_file_names:
                        full_path = os.path.join(DIR_INPUT, file_name)
                        if os.path.exists(full_path):
                            # arcname=file_name にすることで、tar内ではルート直下に配置される
                            tar.add(full_path, arcname=file_name)
        
        return output_path

    except Exception as e:
        st.error(f"圧縮処理中にエラーが発生しました: {e}")
        return None

# --- 解凍ロジック (BytesIO使用・Internal Error対策済み) ---
def decompress_custom_format(uploaded_file):
    try:
        # 1. バイナリヘッダー確認
        uploaded_file.seek(0)
        magic = uploaded_file.read(len(MAGIC_NUMBER))
        
        if magic != MAGIC_NUMBER:
            try:
                magic_str = magic.decode('ascii', errors='ignore')
            except:
                magic_str = str(magic)
            return False, f"不正なファイル形式です。\n期待値: {MAGIC_NUMBER}\n検出値: {magic_str}..."

        # 2. XZデータ部分をメモリに読み込み
        compressed_body = uploaded_file.read()
        
        with io.BytesIO(compressed_body) as f_in:
            # 3. 解凍 & 展開
            with lzma.open(f_in, "r", format=lzma.FORMAT_XZ) as lzma_file:
                with tarfile.open(fileobj=lzma_file, mode="r") as tar:
                    tar.extractall(path=DIR_EXTRACTED)
        
        return True, "解凍成功"

    except lzma.LZMAError as e:
        return False, f"LZMA Error: {e}"
    except tarfile.ReadError:
        return False, "Tar Error: アーカイブ構造の読み込みに失敗"
    except Exception as e:
        return False, f"Error: {e}"

# --- UI (Streamlit) ---
st.set_page_config(page_title="Extreme Compress V3.2", layout="wide")
init_directories()

st.title("🗜️ Extreme Compression V3.2 (Selectable)")
st.caption("アップロードしたファイルの中から、圧縮するものを選択できます。")

# サイドバー
with st.sidebar:
    st.header("ワークスペース")
    if st.button("🗑️ 全データをクリア", type="primary"):
        clear_workspace()
        st.rerun()
    st.info(f"入力: {len(os.listdir(DIR_INPUT))} | 解凍済: {len(os.listdir(DIR_EXTRACTED))}")

tab1, tab2 = st.tabs(["📤 圧縮 (Compress)", "📥 解凍 (Decompress)"])

# === 圧縮タブ ===
with tab1:
    col1, col2 = st.columns(2)
    
    # --- 左カラム: アップロード ---
    with col1:
        st.subheader("1. ファイルをアップロード")
        uploaded_files = st.file_uploader("inputフォルダに追加", accept_multiple_files=True)
        
        if uploaded_files:
            for uf in uploaded_files:
                # 同名ファイルは上書き保存
                with open(os.path.join(DIR_INPUT, uf.name), "wb") as f:
                    f.write(uf.getbuffer())
            # アップロード後に一度rerunしてリストを更新させるとスムーズですが
            # ここではそのまま処理続行
            
        # 既存ファイル一覧の取得
        current_files = sorted(os.listdir(DIR_INPUT))
        
        if not current_files:
            st.info("ファイルがありません。アップロードしてください。")
            selected_files = []
        else:
            st.write("---")
            st.subheader("2. 圧縮対象を選択")
            # マルチセレクトボックス (デフォルトで全選択)
            selected_files = st.multiselect(
                "リストから選択:", 
                current_files, 
                default=current_files
            )
            st.caption(f"{len(selected_files)} 個のファイルを選択中")

    # --- 右カラム: 実行とダウンロード ---
    with col2:
        st.subheader("3. 圧縮実行")
        out_name = st.text_input("出力ファイル名", value="archive")
        
        # ボタン: ファイルが選択されている時のみ有効
        if st.button("🚀 圧縮開始", disabled=len(selected_files) == 0):
            with st.spinner("圧縮中... (V3 XZ Format)"):
                # 選択されたファイルリストを渡す
                result_path = compress_selected_files(selected_files, out_name)
            
            if result_path and os.path.exists(result_path):
                # 圧縮率計算 (選択されたファイルの合計サイズと比較)
                total_orig_size = sum(os.path.getsize(os.path.join(DIR_INPUT, f)) for f in selected_files)
                compressed_size = os.path.getsize(result_path)
                
                ratio = (1 - (compressed_size / total_orig_size)) * 100 if total_orig_size > 0 else 0
                
                st.success(f"完了！")
                m1, m2, m3 = st.columns(3)
                m1.metric("元サイズ", f"{total_orig_size:,} B")
                m2.metric("圧縮後", f"{compressed_size:,} B")
                m3.metric("削減率", f"{ratio:.2f}%")
                
                with open(result_path, "rb") as f:
                    st.download_button(
                        label="⬇️ ダウンロード (.mycmp)",
                        data=f,
                        file_name=os.path.basename(result_path),
                        mime="application/octet-stream"
                    )

# === 解凍タブ ===
with tab2:
    st.subheader("検証と解凍")
    uploaded_archive = st.file_uploader("ファイルをアップロード (拡張子不問)", type=None)
    
    if uploaded_archive:
        file_name = uploaded_archive.name
        file_ext = os.path.splitext(file_name)[1].lower()
        st.info(f"File: `{file_name}`")

        if st.button("🔍 解凍開始"):
            if file_ext != ".mycmp":
                st.warning(f"Note: 拡張子が違いますが ({file_ext}) 解析を試みます。")
            
            with st.spinner("展開中..."):
                success, msg = decompress_custom_format(uploaded_archive)
            
            if success:
                st.balloons()
                st.success(f"✅ {msg}")
                
                # ダウンロードリスト
                extracted_files = []
                for root, dirs, files in os.walk(DIR_EXTRACTED):
                    for file in files:
                        extracted_files.append(os.path.join(root, file))
                
                if extracted_files:
                    st.write("📂 **解凍されたファイル:**")
                    for path in extracted_files:
                        rel_path = os.path.relpath(path, DIR_EXTRACTED)
                        with open(path, "rb") as f:
                            st.download_button(
                                label=f"⬇️ {rel_path}",
                                data=f,
                                file_name=os.path.basename(path),
                                key=f"dl_{rel_path}"
                            )
            else:
                st.error(f"❌ {msg}")
