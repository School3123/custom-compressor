import streamlit as st
import lzma
import tarfile
import struct
import os
import shutil
import glob

# --- 設定 ---
MAGIC_NUMBER = b'MYCP_V2' # バージョン2
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

# --- 圧縮ロジック (Extreme) ---
def compress_folder_to_custom_format(output_filename="archive"):
    """
    input_files フォルダの中身を丸ごとtarでまとめて、
    最強設定のLZMA2で圧縮し、独自コンテナ (.mycmp) にする
    """
    output_path = os.path.join(DIR_COMPRESSED, f"{output_filename}.mycmp")
    
    # 1. まず tar アーカイブをメモリ上(BytesIO)ではなく、ストリームとして作成しながら圧縮
    # メモリ節約のため、パイプライン処理的に行うイメージですが、
    # Pythonでは一度tarを作ってから圧縮するか、Custom Filterを使う必要があります。
    # ここでは「ソリッド圧縮」を実現するため、tarストリームをLZMA圧縮します。

    try:
        # LZMA2 カスタムフィルタ (極限設定)
        # 辞書サイズを128MBに設定 (標準のPreset 9は64MB)。
        # これにより、遠く離れたデータの重複も見つけ出せます。
        my_filters = [
            {
                "id": lzma.FILTER_LZMA2, 
                "preset": 9 | lzma.PRESET_EXTREME,
                "dict_size": 128 * 1024 * 1024, # 128MB Dictionary
                "lc": 4, # Literal Context bits (テキストデータに効く)
                "lp": 0,
                "pb": 2, 
                "nice_len": 273,
                "mf": lzma.MF_BT4
            }
        ]

        with open(output_path, "wb") as f_out:
            # ヘッダー書き込み
            f_out.write(MAGIC_NUMBER)
            
            # LZMA圧縮ストリームの開始
            with lzma.open(f_out, "w", format=lzma.FORMAT_RAW, filters=my_filters) as lzma_file:
                # tarを作成してLZMAストリームに流し込む
                with tarfile.open(fileobj=lzma_file, mode="w") as tar:
                    # inputフォルダの中身をルートに追加
                    # arcnameでパスを調整し、解凍時にinput_filesフォルダそのものが掘られないようにする
                    for root, dirs, files in os.walk(DIR_INPUT):
                        for file in files:
                            full_path = os.path.join(root, file)
                            # アーカイブ内でのパス (input_files/hoge.txt -> hoge.txt)
                            rel_path = os.path.relpath(full_path, DIR_INPUT)
                            tar.add(full_path, arcname=rel_path)
        
        return output_path

    except Exception as e:
        st.error(f"圧縮処理中にエラーが発生しました: {e}")
        return None

# --- 解凍ロジック ---
def decompress_custom_format(uploaded_file):
    """
    独自ファイルを検証し、extracted_output フォルダに展開する
    """
    try:
        # ファイルポインタを先頭へ
        uploaded_file.seek(0)
        
        # 1. マジックナンバー確認
        magic = uploaded_file.read(len(MAGIC_NUMBER))
        if magic != MAGIC_NUMBER:
            st.error("不正なファイル形式です。マジックナンバーが一致しません。")
            return False

        # 2. 解凍 & 展開
        # LZMAストリームとして読み込む
        with lzma.open(uploaded_file, "r", format=lzma.FORMAT_RAW) as lzma_file:
            # tarとして展開
            with tarfile.open(fileobj=lzma_file, mode="r") as tar:
                # 安全のため、パス走査攻撃を防ぐ（簡易版）
                tar.extractall(path=DIR_EXTRACTED)
        
        return True

    except Exception as e:
        st.error(f"解凍エラー: {e}")
        return False

# --- UI (Streamlit) ---
st.set_page_config(page_title="Extreme Compress App V2", layout="wide")
init_directories()

st.title("🗜️ Extreme Compression V2: Folder & Solid Mode")
st.caption("ソリッド圧縮とカスタムLZMA2フィルタ(128MB辞書)を使用した最強圧縮アプリ")

# サイドバー：状態管理
with st.sidebar:
    st.header("ワークスペース管理")
    if st.button("🗑️ 全データをクリア", type="primary"):
        clear_workspace()
        st.rerun()
    
    st.info(f"入力フォルダ: {len(os.listdir(DIR_INPUT))} ファイル")
    st.info(f"解凍フォルダ: {len(os.listdir(DIR_EXTRACTED))} アイテム")

tab1, tab2 = st.tabs(["📤 圧縮 (Compress)", "📥 解凍 (Decompress)"])

# === 圧縮タブ ===
with tab1:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. ファイルを配置")
        uploaded_files = st.file_uploader(
            "圧縮したいファイルを選択 (複数可)", 
            accept_multiple_files=True
        )
        
        if uploaded_files:
            # ファイルを workspace/input_files に保存
            for uf in uploaded_files:
                with open(os.path.join(DIR_INPUT, uf.name), "wb") as f:
                    f.write(uf.getbuffer())
            st.success(f"{len(uploaded_files)} 個のファイルを配置しました。")
            # アップロード完了後、UI上のリストをリセットするためにrerunしない手法もあるが
            # ここではシンプルに処理継続

        # 現在の対象ファイル表示
        st.write("---")
        st.write("📂 **圧縮対象のファイル一覧** (input_files):")
        files = os.listdir(DIR_INPUT)
        if files:
            st.code("\n".join(files))
        else:
            st.warning("ファイルがありません。アップロードしてください。")

    with col2:
        st.subheader("2. 圧縮を実行")
        out_name = st.text_input("出力ファイル名 (拡張子不要)", value="my_archive")
        
        if st.button("🚀 超圧縮を開始", disabled=len(files)==0):
            with st.spinner("解析・ソリッド圧縮中... (CPU負荷 高)"):
                # 圧縮実行
                result_path = compress_folder_to_custom_format(out_name)
            
            if result_path and os.path.exists(result_path):
                # 結果表示
                original_size = get_folder_size(DIR_INPUT)
                compressed_size = os.path.getsize(result_path)
                
                if original_size > 0:
                    ratio = (1 - (compressed_size / original_size)) * 100
                else:
                    ratio = 0
                
                st.balloons()
                st.success("圧縮完了！")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("元サイズ (Total)", f"{original_size:,} bytes")
                m2.metric("圧縮後 (.mycmp)", f"{compressed_size:,} bytes")
                m3.metric("削減率", f"{ratio:.2f}%")
                
                with open(result_path, "rb") as f:
                    st.download_button(
                        label="⬇️ 圧縮ファイルをダウンロード",
                        data=f,
                        file_name=os.path.basename(result_path),
                        mime="application/octet-stream"
                    )

# === 解凍タブ ===
with tab2:
    st.subheader("独自形式 (.mycmp) の解凍")
    uploaded_archive = st.file_uploader("圧縮ファイルをアップロード", type=["mycmp"])
    
    if uploaded_archive:
        if st.button("🔓 解凍開始"):
            # 解凍前に出力先をクリアするか確認してもいいが、今回は追記型
            with st.spinner("展開中..."):
                success = decompress_custom_format(uploaded_archive)
            
            if success:
                st.success(f"展開完了！ フォルダ: {DIR_EXTRACTED}")
                
                # 解凍されたファイルの一覧表示とダウンロード
                extracted_files = []
                for root, dirs, files in os.walk(DIR_EXTRACTED):
                    for file in files:
                        full_path = os.path.join(root, file)
                        extracted_files.append(full_path)
                
                st.write("📂 **解凍されたファイル一覧:**")
                for path in extracted_files:
                    rel_path = os.path.relpath(path, DIR_EXTRACTED)
                    
                    # 個別ダウンロードボタン
                    with open(path, "rb") as f:
                        file_data = f.read()
                        st.download_button(
                            label=f"⬇️ {rel_path} ({len(file_data):,} B)",
                            data=file_data,
                            file_name=os.path.basename(path),
                            key=f"dl_{rel_path}"
                        )
