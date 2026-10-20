# StemForge Studio 2.0 — Portable (Windows / Mac / Linux)

**ব্যবহারকারীর কম্পিউটারে Python, FFmpeg, pip, Terminal setup, বা Demucs আলাদা install করতে হবে না।** Windows-এর `.exe`, Mac-এর `.app` এবং Linux-এর runnable application-এ এই জিনিসগুলো bundled থাকে। গান বা ভিডিও browser-based app-এ Drag & Drop করে Stem export করা যাবে।

> **এই ZIP-টি Build Kit / সম্পূর্ণ source project।** এখানে এখনও Windows `.exe` বা macOS `.app` binary build করা নেই। নিচের GitHub Actions workflow চালালে আলাদা operating system-এর computer ছাড়াই GitHub-এর Windows/Mac/Linux runner-এ ready-to-run packages তৈরি হবে। **যে কেউ সেই resulting package চালাবে, তাকে Python/FFmpeg install করতে হবে না।**

## ১. Ready-to-run app ব্যবহার করবেন যেভাবে

একবার automated build হলে GitHub Actions-এর **Artifacts** থেকে প্রয়োজনীয় OS-এর archive download করুন:

| আপনার OS | Download package | চালানোর নিয়ম |
| --- | --- | --- |
| Windows (64-bit) | `StemForge-Studio-Windows-x64.zip` | Extract → `StemForge Studio` folder → double-click `StemForge Studio.exe` |
| macOS Intel | `StemForge-Studio-macOS-x64.zip` | Extract → `StemForge Studio.app` → open |
| macOS Apple Silicon (M1/M2/M3/M4+) | `StemForge-Studio-macOS-arm64.zip` | Extract → `StemForge Studio.app` → open |
| Linux (64-bit) | `StemForge-Studio-Linux-x64.tar.gz` | Extract → `StemForge Studio/StemForge Studio` executable চালান |

অ্যাপ চালু হলে default browser-এ লোকাল `http://127.0.0.1:8765` খুলবে (এই port ব্যস্ত থাকলে অন্য একটি free port নিজে নির্বাচন করবে)। Audio বা Video upload → 4-Stem / 6-Stem নির্বাচন → Start → গান আলাদা হলে individual audio বা ZIP download করুন। Export files আপনার `Home/StemForge Studio/Exports` folder-এও থাকবে। অ্যাপ বন্ধ করতে নিচের **CLOSE APP** button চাপুন।

**প্রথমবার প্রতিটি আলাদা AI Model নির্বাচন করলে শুধু model weights download হবে** — internet connection এবং free disk space লাগবে। এটা Python বা FFmpeg installation নয়। পরেরবার একই model-এর cached weights ব্যবহার হবে। CPU-তে processing তুলনামূলক ধীর হতে পারে।

## ২. আপনার জন্য ৪টি actual app তৈরি করবেন (GitHub দিয়ে)

1. GitHub-এ একটি **নতুন repository** তৈরি করুন।
2. এই `StemForge_Studio_Portable` folder-এর সব file সেই repository-তে upload/push করুন, বিশেষত `.github/workflows/build-portable.yml` path-টি **হুবহু** থাকতে হবে। (Git client ব্যবহার করলে folder upload সহজ হয়।)
3. Repository-র **Actions** tab → **Build standalone StemForge apps (no Python/FFmpeg for users)** → **Run workflow** নির্বাচন করুন।
4. Workflow সফল হলে সংশ্লিষ্ট run-এর **Artifacts** section থেকে Windows-x64, Linux-x64, macOS-Intel, macOS-Apple-Silicon package পাবেন। প্রতিটিতে OS-specific ready-to-run app থাকবে।
5. প্রয়োজনীয় package অন্য কাউকে দিলেও তার Python/FFmpeg install করতে হবে না।

GitHub Actions build-এর সময় GitHub-এর build runner-এ Python, PyTorch, Demucs, FFmpeg binary এবং PyInstaller আনা হয়। **User-এর system-এ এগুলোর installation হয় না।** Compiled app size অনেক বড় হওয়া স্বাভাবিক (PyTorch library bundled)। Mac Apple Silicon runner GitHub account/plan বা repository-এর runner quota অনুযায়ী unavailable হতে পারে; সেক্ষেত্রে Mac-এর অন্য runner বা নিজস্ব Apple Silicon Mac দিয়ে build করতে হবে। GitHub build-এর সময় internet প্রয়োজন।

**গুরুত্বপূর্ণ:** এ মুহূর্তে native Windows বা Mac machine-এ binary পরীক্ষা করা হয়নি; কাজেই automated workflow সফল হবে এমন নিশ্চয়তা দেয়া যাচ্ছে না। Workflow-তে validation ও packaged self-test রাখা আছে।

## ৩. কী কী কাজ করে

- Supported files: FFmpeg can decode যেসব Audio/Video যেমন MP3, WAV, FLAC, M4A, AAC, OGG, MP4, MKV, MOV, WEBM ইত্যাদি। **সব ফরম্যাট নিঃশর্তে নয়**; unsupported codec/DRM ফাইল ব্যর্থ হতে পারে।
- Model options: `htdemucs` (4 stems), `htdemucs_ft` (enhanced 4 stems), `htdemucs_6s` (6 stems)।
- 4 stems: Vocal / Drums (Beat) / Bass / Other. 6 stems: উপরের সঙ্গে Guitar / Piano। Piano separation সবসময় পরিষ্কার নয়।
- অতিরিক্ত: Instrumental (no vocal) ও Rhythm (drum + bass) তৈরি হয়।
- WAV 24-bit, MP3 320 kbps, FLAC export; প্রতিটি আলাদা preview/download, সবগুলো এক ZIP।
- Batch queue, local preview, progress stages, CLOSE APP, 2 GB maximum per file।
- সব processing নিজের computer-এ হয়, তৃতীয় পক্ষের service-এ media upload হয় না। AI model প্রথমবার download হয়।

## ৪. Build Developer-দের জন্য

এই project-এ `build_portable.py`, `package_portable.py` এবং `.github/workflows/build-portable.yml` দেয়া আছে। `requirements-build.txt` কেবল GitHub runner বা developer-এর জন্য। Ready app-এর user-এর জন্য নয়। `python app.py --self-test` runtime যাচাই করে, `python -m unittest discover -s tests -v` pipeline test করে, আর compiled binary-কে `--self-test` দিয়ে CI-তে যাচাই করা হয়।

PyInstaller cross-compile করে না; macOS `.app` বানানোর জন্য macOS-এ, Windows `.exe` বানানোর জন্য Windows-এ build হতে হবে—GitHub Actions matrix সেটাই করে। Details: https://pyinstaller.org/en/stable/operating-mode.html

**Code sign / notarization:** এই project-এ কোন Apple Developer certificate বা Windows code-signing certificate অন্তর্ভুক্ত নেই। Unsigned Windows app-এর SmartScreen prompt বা macOS-এর Gatekeeper prompt দেখা যেতে পারে; official signing/notarization ছাড়া এগুলো পুরোপুরি দূর করা যায় না। অজানা উৎসের অ্যাপের জন্য OS-এর global security বন্ধ করবেন না।

## ৫. Limitations

- Perfect separation guarantee নেই; mixed instruments and reverb bleed হতে পারে।
- MP3/WAV/FLAC stem export supported; stems আবার video format-এ export করা হয় না। Video input-এর audio track extract করা হয়।
- NVIDIA CUDA acceleration-এর মতো GPU-specific wheels default build-এ দেওয়া হয়নি; Windows/Linux এর portable build CPU-only PyTorch ব্যবহার করে।
- Runtime needs sufficient RAM/disk. Model weights first usage download; offline first-launch separation possible নয় যদি cache empty হয়।
- Mac/Windows/Linux installer file build করে দেওয়ার সক্ষমতা এই environment-এ নেই; তার জন্য workflow সংযুক্ত আছে।

## নিরাপত্তা ও লাইসেন্স

Only process audio/video you have rights or permission to use. Demucs upstream MIT; bundled runtime dependencies and FFmpeg have their own licenses. See respective upstream licenses for redistribution/commercial distribution rules.
