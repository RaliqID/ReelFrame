# iOS Mobile Companion — ReelFrame

> ⚠️ **For iOS Support**: ReelFrame runs the AI processing on your **Windows PC** (GPU-powered). The iOS app connects to the same WiFi network and uses your PC as the backend engine.

## How It Works

```
iPhone / iPad (iOS App)
      │  WiFi (same network)
      ▼
[ReelFrame Server on Windows PC] ──▶ RTX 3050 GPU ──▶ 4K Output
```

---

## iOS Companion App Architecture

ReelFrame's iOS companion is a **React Native + Expo** app that:
1. Discovers the ReelFrame server on local WiFi
2. Lets you browse and select videos/photos from iOS Camera Roll
3. Queues upscale jobs on the PC GPU
4. Downloads the finished 4K file directly to Photos

### App Tech Stack
- **React Native + Expo** (cross-platform, no Mac needed for dev)
- **react-native-vision-camera** for live preview
- **expo-media-library** for Camera Roll access
- **react-native-fs** for file transfer

---

## Quick Setup for iOS

### Prerequisites
- iPhone / iPad running iOS 16+
- Windows PC with ReelFrame installed
- Both on same WiFi network
- [Expo Go](https://apps.apple.com/app/expo-go/id982107779) installed on iPhone

### Steps

1. **On your PC**, run ReelFrame with network binding:
   ```powershell
   .\run_gui.bat
   ```
   The server will show your local IP, e.g.:
   ```
   Network: http://192.168.100.62:7860
   ```

2. **On your iPhone**, open Expo Go and scan the QR code printed in console (or navigate to the IP in Safari).

3. The ReelFrame mobile companion interface will load — you can:
   - Browse Camera Roll
   - Select reels / photos to upscale
   - Monitor real-time GPU progress from your phone
   - Download finished 4K files to your Camera Roll

---

## iOS App Source (React Native)

The iOS companion source is located in `./ios-app/` and can be launched with:

```bash
cd ios-app
npm install
npx expo start
```

Scan the QR code with Expo Go on your iPhone.

---

## Author

**Raliq Hidayat BM3**
- GitHub: [@kouji999](https://github.com/kouji999)
