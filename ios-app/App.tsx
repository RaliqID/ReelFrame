import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  ScrollView,
  Alert,
  ActivityIndicator,
  SafeAreaView,
  FlatList,
  StatusBar,
  Platform,
} from 'react-native';
import * as MediaLibrary from 'expo-media-library';
import * as FileSystem from 'expo-file-system';

// =============================================================================
// Types
// =============================================================================
interface Job {
  job_id: string;
  input_filename: string;
  output_filename: string;
  status: 'queued' | 'processing' | 'completed' | 'error' | 'cancelled';
  progress: number;
  fps: number;
  eta: number;
  current_frame: number;
  total_frames: number;
  log: string;
  error?: string;
}

interface GpuInfo {
  cuda_available: boolean;
  gpu_name: string;
  vram_gb: number;
  vram_used_gb?: number;
  cuda_version?: string;
}

// =============================================================================
// Config
// =============================================================================
const STORAGE_KEY = 'reelframe_server_ip';
const DEFAULT_MODEL = 'realesr-general-x4v3.pth';

// =============================================================================
// Helpers
// =============================================================================
function useServerUrl(ip: string, port = 7860): string {
  return `http://${ip}:${port}`;
}

// =============================================================================
// Components
// =============================================================================

const PRESETS = [
  { id: 'reels-4k', label: 'Reels 4K', emoji: '📱', desc: '9:16 Vertical', model: DEFAULT_MODEL, scale: '2x', cq: '19' },
  { id: 'cinema-4k', label: 'Cinema 4K', emoji: '🎬', desc: '16:9 Wide', model: DEFAULT_MODEL, scale: '2x', cq: '18' },
  { id: 'photo-crisp', label: 'Photo Sharp', emoji: '📷', desc: 'Ultra Detail', model: 'RealESRGAN_x4plus.pth', scale: '4x', cq: '16' },
  { id: 'anime', label: 'Anime', emoji: '🎌', desc: '2D Artwork', model: 'RealESRGAN_x4plus_anime_6B.pth', scale: '2x', cq: '20' },
];

// =============================================================================
// Main App
// =============================================================================
export default function App() {
  const [serverIp, setServerIp] = useState('192.168.100.62');
  const [ipInput, setIpInput] = useState('192.168.100.62');
  const [screen, setScreen] = useState<'setup' | 'main'>('setup');

  const [tab, setTab] = useState<'upscale' | 'queue' | 'history'>('upscale');
  const [gpuInfo, setGpuInfo] = useState<GpuInfo | null>(null);
  const [selectedPreset, setSelectedPreset] = useState(PRESETS[0]);

  const [jobs, setJobs] = useState<Job[]>([]);
  const [history, setHistory] = useState<Job[]>([]);
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const BASE_URL = useServerUrl(serverIp);

  // ── Media picker ──────────────────────────────────────────────────────────
  const [mediaPermission, requestMediaPermission] = MediaLibrary.usePermissions();

  const pickMedia = useCallback(async () => {
    const perm = await requestMediaPermission();
    if (!perm.granted) {
      Alert.alert('Permission Required', 'Please allow access to Media Library.');
      return;
    }
    // Expo MediaLibrary: pick from camera roll
    // Note: We'll do a simple assets query and pick first video for demo
    Alert.alert(
      'Select Media',
      'Pick a video or image from your Photos app, then tap Upload.',
      [{ text: 'OK' }]
    );
  }, [requestMediaPermission]);

  // ── Server connect ─────────────────────────────────────────────────────────
  const connectToServer = useCallback(async (ip: string) => {
    try {
      const res = await fetch(`http://${ip}:7860/api/gpu-info`, { signal: AbortSignal.timeout(4000) });
      if (!res.ok) throw new Error('Not OK');
      const data: GpuInfo = await res.json();
      setGpuInfo(data);
      setServerIp(ip);
      setScreen('main');
    } catch {
      Alert.alert('Connection Failed', `Cannot reach ReelFrame at ${ip}:7860\n\nMake sure:\n• PC is on same WiFi\n• run_app.bat is running`);
    }
  }, []);

  // ── Poll jobs ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (screen !== 'main') return;
    const poll = setInterval(async () => {
      try {
        const [jobsRes, histRes] = await Promise.all([
          fetch(`${BASE_URL}/api/jobs`),
          fetch(`${BASE_URL}/api/history`),
        ]);
        const jobsData = await jobsRes.json();
        const histData = await histRes.json();
        setJobs(Object.values(jobsData));
        setHistory(Array.isArray(histData) ? histData.slice().reverse() : []);
      } catch {}
    }, 1500);
    return () => clearInterval(poll);
  }, [screen, BASE_URL]);

  // ── Cancel job ─────────────────────────────────────────────────────────────
  const cancelJob = useCallback(async (jobId: string) => {
    try {
      await fetch(`${BASE_URL}/api/job/${jobId}`, { method: 'DELETE' });
    } catch {}
  }, [BASE_URL]);

  // ── Download result ────────────────────────────────────────────────────────
  const downloadResult = useCallback(async (jobId: string, filename: string) => {
    const downloadUrl = `${BASE_URL}/api/download/${jobId}`;
    const dest = `${FileSystem.documentDirectory}${filename}`;
    const res = await FileSystem.downloadAsync(downloadUrl, dest);
    if (res.status === 200) {
      await MediaLibrary.saveToLibraryAsync(res.uri);
      Alert.alert('Downloaded! ✅', `"${filename}" saved to Photos.`);
    } else {
      Alert.alert('Download failed', 'Could not fetch the file.');
    }
  }, [BASE_URL]);

  // ── Render: Setup Screen ───────────────────────────────────────────────────
  if (screen === 'setup') {
    return (
      <SafeAreaView style={styles.setupContainer}>
        <StatusBar barStyle="light-content" backgroundColor="#070a12" />
        <Text style={styles.logo}>🎬 ReelFrame</Text>
        <Text style={styles.logoSub}>Local 4K AI Upscaler</Text>
        <Text style={styles.setupInstructions}>
          1. Open <Text style={styles.bold}>run_app.bat</Text> on your Windows PC{'\n'}
          2. Look for the <Text style={styles.bold}>Network:</Text> IP address{'\n'}
          3. Enter it below and tap Connect
        </Text>
        <TextInput
          style={styles.ipInput}
          value={ipInput}
          onChangeText={setIpInput}
          placeholder="192.168.x.x"
          placeholderTextColor="#64748b"
          keyboardType="numeric"
          returnKeyType="done"
          onSubmitEditing={() => connectToServer(ipInput)}
        />
        <TouchableOpacity style={styles.btnConnect} onPress={() => connectToServer(ipInput)}>
          <Text style={styles.btnConnectText}>Connect to ReelFrame PC</Text>
        </TouchableOpacity>
        <Text style={styles.footerSetup}>By Raliq Hidayat BM3</Text>
      </SafeAreaView>
    );
  }

  // ── Render: Main App ───────────────────────────────────────────────────────
  const activeJobs = jobs.filter(j => j.status === 'processing' || j.status === 'queued');
  const completedJobs = history.filter(j => j.status === 'completed');

  return (
    <SafeAreaView style={styles.mainContainer}>
      <StatusBar barStyle="light-content" backgroundColor="#070a12" />

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerLogo}>🎬 ReelFrame</Text>
        {gpuInfo && (
          <View style={styles.gpuBadge}>
            <View style={styles.statusDot} />
            <Text style={styles.gpuText}>{gpuInfo.gpu_name.replace('NVIDIA ', '').replace('GeForce ', '')} {gpuInfo.vram_gb}GB</Text>
          </View>
        )}
      </View>

      {/* Tab Bar */}
      <View style={styles.tabBar}>
        {(['upscale', 'queue', 'history'] as const).map(t => (
          <TouchableOpacity key={t} style={[styles.tabBtn, tab === t && styles.tabBtnActive]} onPress={() => setTab(t)}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
              {t === 'upscale' ? '⚡ Upscale' : t === 'queue' ? `🔄 Queue${activeJobs.length > 0 ? ` (${activeJobs.length})` : ''}` : `📋 History`}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Tab: Upscale */}
      {tab === 'upscale' && (
        <ScrollView style={styles.content} contentContainerStyle={{ paddingBottom: 40 }}>
          <Text style={styles.sectionTitle}>Select Preset</Text>
          <View style={styles.presetsRow}>
            {PRESETS.map(p => (
              <TouchableOpacity
                key={p.id}
                style={[styles.presetCard, selectedPreset.id === p.id && styles.presetCardActive]}
                onPress={() => setSelectedPreset(p)}
              >
                <Text style={styles.presetEmoji}>{p.emoji}</Text>
                <Text style={styles.presetLabel}>{p.label}</Text>
                <Text style={styles.presetDesc}>{p.desc}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <TouchableOpacity style={styles.dropzone} onPress={pickMedia}>
            <Text style={styles.dropzoneIcon}>📂</Text>
            <Text style={styles.dropzoneTitle}>Tap to Browse Media</Text>
            <Text style={styles.dropzoneSubtitle}>Videos & Photos from Camera Roll</Text>
          </TouchableOpacity>

          <View style={styles.infoCard}>
            <Text style={styles.infoTitle}>Selected Preset: {selectedPreset.label}</Text>
            <Text style={styles.infoText}>Model: {selectedPreset.model}</Text>
            <Text style={styles.infoText}>Scale: {selectedPreset.scale} | Quality: CQ {selectedPreset.cq}</Text>
            <Text style={styles.infoText}>Tiling: 512px (RTX 3050 Safe ✓)</Text>
          </View>

          <Text style={styles.noteText}>
            📡 Connected to ReelFrame PC at <Text style={styles.bold}>{serverIp}</Text>{'\n'}
            Processing happens on your <Text style={styles.bold}>RTX 3050</Text> GPU.
          </Text>
        </ScrollView>
      )}

      {/* Tab: Queue */}
      {tab === 'queue' && (
        <FlatList
          data={activeJobs}
          keyExtractor={j => j.job_id}
          contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>✅</Text>
              <Text style={styles.emptyText}>No active jobs</Text>
            </View>
          }
          renderItem={({ item }) => (
            <View style={styles.jobCard}>
              <Text style={styles.jobName}>{item.input_filename}</Text>
              <Text style={styles.jobStatus}>{item.status} — {item.progress.toFixed(1)}%</Text>
              <View style={styles.progressBg}>
                <View style={[styles.progressFill, { width: `${item.progress}%` as any }]} />
              </View>
              <Text style={styles.jobMeta}>Frame {item.current_frame}/{item.total_frames} | {item.fps.toFixed(1)} fps</Text>
              <TouchableOpacity style={styles.btnCancel} onPress={() => cancelJob(item.job_id)}>
                <Text style={styles.btnCancelText}>Cancel</Text>
              </TouchableOpacity>
            </View>
          )}
        />
      )}

      {/* Tab: History */}
      {tab === 'history' && (
        <FlatList
          data={completedJobs}
          keyExtractor={j => j.job_id}
          contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>📋</Text>
              <Text style={styles.emptyText}>No completed jobs yet</Text>
            </View>
          }
          renderItem={({ item }) => (
            <View style={styles.jobCard}>
              <Text style={styles.jobName}>{item.output_filename}</Text>
              <Text style={styles.jobStatusDone}>✅ Completed</Text>
              <TouchableOpacity
                style={styles.btnDownload}
                onPress={() => downloadResult(item.job_id, item.output_filename)}
              >
                <Text style={styles.btnDownloadText}>⬇️ Download to Photos</Text>
              </TouchableOpacity>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

// =============================================================================
// Styles
// =============================================================================
const C = {
  bg: '#070a12',
  card: 'rgba(15,22,36,0.95)',
  border: 'rgba(255,255,255,0.09)',
  primary: '#6366f1',
  accent: '#10b981',
  text: '#f8fafc',
  muted: '#94a3b8',
  danger: '#ef4444',
};

const styles = StyleSheet.create({
  setupContainer: { flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center', padding: 32 },
  logo: { fontSize: 38, fontWeight: '800', color: C.text, marginBottom: 6 },
  logoSub: { fontSize: 16, color: C.muted, marginBottom: 32 },
  setupInstructions: { fontSize: 14, color: C.muted, textAlign: 'center', lineHeight: 24, marginBottom: 28 },
  bold: { fontWeight: '700', color: C.text },
  ipInput: { width: '100%', backgroundColor: 'rgba(0,0,0,0.4)', borderWidth: 1, borderColor: C.border, borderRadius: 12, color: C.text, fontSize: 18, padding: 14, textAlign: 'center', marginBottom: 16, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  btnConnect: { width: '100%', backgroundColor: C.primary, borderRadius: 12, padding: 16, alignItems: 'center', shadowColor: C.primary, shadowOpacity: 0.5, shadowRadius: 12 },
  btnConnectText: { color: '#fff', fontSize: 16, fontWeight: '700' },
  footerSetup: { position: 'absolute', bottom: 32, fontSize: 12, color: C.muted },

  mainContainer: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 18, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: C.border },
  headerLogo: { fontSize: 20, fontWeight: '800', color: C.text },
  gpuBadge: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: 'rgba(16,185,129,0.12)', borderWidth: 1, borderColor: 'rgba(16,185,129,0.3)', borderRadius: 99, paddingHorizontal: 10, paddingVertical: 5 },
  statusDot: { width: 7, height: 7, borderRadius: 99, backgroundColor: C.accent },
  gpuText: { fontSize: 11, color: '#34d399', fontWeight: '700' },

  tabBar: { flexDirection: 'row', backgroundColor: 'rgba(0,0,0,0.3)', borderBottomWidth: 1, borderBottomColor: C.border },
  tabBtn: { flex: 1, paddingVertical: 12, alignItems: 'center' },
  tabBtnActive: { borderBottomWidth: 2, borderBottomColor: C.primary },
  tabText: { fontSize: 12, color: C.muted, fontWeight: '600' },
  tabTextActive: { color: C.primary },

  content: { flex: 1 },
  sectionTitle: { fontSize: 13, fontWeight: '700', color: C.muted, textTransform: 'uppercase', letterSpacing: 1, margin: 16, marginBottom: 10 },
  presetsRow: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 12, gap: 10 },
  presetCard: { width: '47%', backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: 14, padding: 16, alignItems: 'center' },
  presetCardActive: { borderColor: C.primary, backgroundColor: 'rgba(99,102,241,0.1)' },
  presetEmoji: { fontSize: 28, marginBottom: 4 },
  presetLabel: { fontSize: 14, fontWeight: '700', color: C.text },
  presetDesc: { fontSize: 11, color: C.muted, marginTop: 2 },

  dropzone: { margin: 16, borderWidth: 2, borderColor: C.border, borderStyle: 'dashed', borderRadius: 14, padding: 32, alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.02)' },
  dropzoneIcon: { fontSize: 36, marginBottom: 8 },
  dropzoneTitle: { fontSize: 16, fontWeight: '700', color: C.text },
  dropzoneSubtitle: { fontSize: 13, color: C.muted, marginTop: 4 },

  infoCard: { margin: 16, backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: 14, padding: 16 },
  infoTitle: { fontSize: 14, fontWeight: '700', color: C.text, marginBottom: 8 },
  infoText: { fontSize: 12, color: C.muted, marginBottom: 4, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },

  noteText: { marginHorizontal: 16, fontSize: 12, color: C.muted, lineHeight: 20 },

  emptyState: { paddingTop: 80, alignItems: 'center' },
  emptyIcon: { fontSize: 48, marginBottom: 12 },
  emptyText: { fontSize: 14, color: C.muted },

  jobCard: { backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: 14, padding: 16, marginBottom: 12 },
  jobName: { fontSize: 14, fontWeight: '700', color: C.text, marginBottom: 4 },
  jobStatus: { fontSize: 12, color: C.muted, marginBottom: 8 },
  jobStatusDone: { fontSize: 12, color: C.accent, fontWeight: '600', marginBottom: 10 },
  progressBg: { height: 8, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: 99, overflow: 'hidden', marginBottom: 6 },
  progressFill: { height: '100%', backgroundColor: C.primary, borderRadius: 99 },
  jobMeta: { fontSize: 11, color: C.muted, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },

  btnCancel: { marginTop: 10, backgroundColor: 'rgba(239,68,68,0.15)', borderWidth: 1, borderColor: 'rgba(239,68,68,0.3)', borderRadius: 8, padding: 10, alignItems: 'center' },
  btnCancelText: { color: '#f87171', fontWeight: '700', fontSize: 13 },
  btnDownload: { marginTop: 6, backgroundColor: C.accent, borderRadius: 10, padding: 12, alignItems: 'center' },
  btnDownloadText: { color: '#fff', fontWeight: '700', fontSize: 14 },
});
