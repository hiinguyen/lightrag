import { useState, useEffect, useRef, useCallback } from 'react';
import { Loader2, RefreshCw, File, WifiOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Breadcrumb from '../components/shared/Breadcrumb';
import ProcessingProgressBar from '../components/shared/ProcessingProgressBar';
import {
    DOCUMENT_STATES,
    resolveDocumentState,
    getApprovalStageLabel,
} from '../utils/documentStatus';

// Một tab cho mỗi trạng thái — khớp với STATUS_GROUPS ở
// app/api_compat/documents.py để badge đếm đúng nhóm tài liệu đang xem.
const STATUS_FILTERS = [
    { key: 'pending', state: DOCUMENT_STATES.awaiting_approval },
    { key: 'processing', state: DOCUMENT_STATES.processing },
    { key: 'failed', state: DOCUMENT_STATES.failed },
    { key: 'indexed', state: DOCUMENT_STATES.indexed },
];

const ACTIVE_POLL_MS = 5000;
const IDLE_POLL_MS = 30000;

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function timeAgo(dateStr) {
    if (!dateStr) return '';
    const diffSec = Math.floor((new Date() - new Date(dateStr)) / 1000);
    if (diffSec < 60) return `${diffSec}s trước`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin} phút trước`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h trước`;
    return `${Math.floor(diffHr / 24)} ngày trước`;
}

/* ─── Thẻ thống kê một trạng thái ─── */
function StateStatCard({ state, count, isActive, onClick }) {
    const Icon = state.icon;
    return (
        <button
            type="button"
            onClick={onClick}
            className={`text-left bg-white dark:bg-gray-900 rounded-2xl border p-5 flex items-center gap-4 shadow-sm transition-all hover:shadow-md ${
                isActive
                    ? 'border-primary-400 dark:border-primary-500 ring-2 ring-primary-100 dark:ring-primary-500/20'
                    : 'border-gray-200 dark:border-gray-800'
            }`}
        >
            <div className={`w-12 h-12 rounded-2xl ${state.iconWrap} flex items-center justify-center flex-shrink-0`}>
                <Icon className={`w-6 h-6 ${state.iconColor}`} />
            </div>
            <div className="min-w-0">
                <p className="text-2xl font-black text-gray-900 dark:text-white">{count}</p>
                <p className="text-sm text-gray-500 dark:text-gray-400 truncate">{state.label}</p>
            </div>
        </button>
    );
}

/* ─── Một dòng tài liệu, giao diện đổi theo trạng thái ─── */
function DocumentStatusRow({ doc }) {
    const state = resolveDocumentState(doc);
    const StateIcon = state.icon;
    const isAwaitingApproval = state === DOCUMENT_STATES.awaiting_approval;
    const isFailed = state === DOCUMENT_STATES.failed;

    return (
        <div className={`px-6 py-4 border-l-4 transition-colors ${
            isFailed
                ? 'border-l-red-500 bg-red-50/40 dark:bg-red-500/5 hover:bg-red-50 dark:hover:bg-red-500/10'
                : isAwaitingApproval
                ? 'border-l-amber-400 hover:bg-amber-50/50 dark:hover:bg-amber-500/5'
                : state === DOCUMENT_STATES.indexed
                ? 'border-l-emerald-400 hover:bg-gray-50 dark:hover:bg-gray-800/50'
                : 'border-l-primary-400 hover:bg-gray-50 dark:hover:bg-gray-800/50'
        }`}>
            <div className="flex items-center justify-between gap-4">
                {/* Thông tin tệp */}
                <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className={`w-10 h-10 rounded-xl ${state.iconWrap} flex items-center justify-center flex-shrink-0`}>
                        <File className={`w-5 h-5 ${state.iconColor}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                            {doc.name}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                            <span className="text-xs text-gray-400">{doc.uploader_name}</span>
                            {doc.department_name && (
                                <>
                                    <span className="text-gray-300 dark:text-gray-600 text-xs">·</span>
                                    <span className="text-xs text-gray-400">{doc.department_name}</span>
                                </>
                            )}
                            <span className="text-gray-300 dark:text-gray-600 text-xs">·</span>
                            <span className="text-xs text-gray-400">
                                {doc.file_type?.toUpperCase()} · {formatBytes(doc.file_size)}
                            </span>
                            <span className="text-gray-300 dark:text-gray-600 text-xs">·</span>
                            <span className="text-xs text-gray-400">{timeAgo(doc.created_at)}</span>
                        </div>
                    </div>
                </div>

                {/* Trạng thái */}
                <div className="flex-shrink-0 w-80 flex justify-end">
                    {isAwaitingApproval ? (
                        <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border ${state.badge}`}>
                            <StateIcon className="w-3.5 h-3.5" />
                            {getApprovalStageLabel(doc.approval_status)}
                        </span>
                    ) : (
                        <ProcessingProgressBar
                            status={doc.status}
                            chunkCount={doc.chunk_count}
                            errorMessage={doc.error_message}
                        />
                    )}
                </div>
            </div>

            {/* Chi tiết lỗi + hướng dẫn xử lý tiếp */}
            {isFailed && (
                <div className="mt-3 ml-13 px-3 py-2.5 rounded-lg bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30">
                    <div className="flex items-start gap-2">
                        <StateIcon className="w-3.5 h-3.5 text-red-500 flex-shrink-0 mt-0.5" />
                        <div className="min-w-0">
                            <p className="text-xs font-semibold text-red-700 dark:text-red-400">
                                {doc.error_message || 'Xử lý tài liệu thất bại'}
                            </p>
                            <p className="text-xs text-red-500/80 dark:text-red-400/70 mt-1">
                                Tài liệu đã được trả về {getApprovalStageLabel(doc.approval_status).toLowerCase()} — phê duyệt lại để xử lý lại.
                            </p>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

export default function ProcessingStatus() {
    const { authFetch } = useAuth();
    const [docs, setDocs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [isOnline, setIsOnline] = useState(navigator.onLine);
    const [activeFilter, setActiveFilter] = useState('processing');
    const [counts, setCounts] = useState({ all: 0, pending: 0, processing: 0, indexed: 0, failed: 0 });
    const pollingRef = useRef(null);

    const fetchDocs = useCallback(async (filterKey) => {
        try {
            const res = await authFetch(`/api/documents/processing-status?filter=${filterKey ?? 'all'}`);
            if (res.ok) {
                const data = await res.json();
                setDocs(data.items || []);
                if (data.counts) setCounts(data.counts);
            }
        } catch { /* silent — lần poll kế tiếp sẽ thử lại */ }
    }, [authFetch]);

    const handleRefresh = async () => {
        setRefreshing(true);
        await fetchDocs(activeFilter);
        setRefreshing(false);
    };

    const handleFilterChange = (key) => {
        setActiveFilter(key);
        fetchDocs(key);
    };

    useEffect(() => {
        let cancelled = false;
        fetchDocs('processing').finally(() => {
            if (!cancelled) setLoading(false);
        });
        return () => { cancelled = true; };
    }, [fetchDocs]);

    // Poll nhanh khi còn tài liệu đang chạy trong pipeline, chậm lại khi đứng yên
    const hasActive = counts.processing > 0;
    useEffect(() => {
        pollingRef.current = setInterval(
            () => fetchDocs(activeFilter),
            hasActive ? ACTIVE_POLL_MS : IDLE_POLL_MS,
        );
        return () => clearInterval(pollingRef.current);
    }, [hasActive, fetchDocs, activeFilter]);

    useEffect(() => {
        const onOnline = () => setIsOnline(true);
        const onOffline = () => setIsOnline(false);
        window.addEventListener('online', onOnline);
        window.addEventListener('offline', onOffline);
        return () => {
            window.removeEventListener('online', onOnline);
            window.removeEventListener('offline', onOffline);
        };
    }, []);

    const activeState = STATUS_FILTERS.find(f => f.key === activeFilter)?.state;

    return (
        <div className="space-y-6 px-2 md:px-4">
            <div className="px-2 pt-4">
                <Breadcrumb items={[
                    { label: 'Tổng quan', href: '/dashboard' },
                    { label: 'Tiến trình xử lý' },
                ]} />
            </div>

            {/* ── Header ── */}
            <div className="flex items-center justify-between px-2">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                        Tiến trình xử lý
                    </h1>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                        Theo dõi trạng thái xử lý tài liệu trong phòng ban của bạn
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ${
                        hasActive
                            ? 'bg-green-50 border-green-200 text-green-700 dark:bg-green-500/10 dark:border-green-500/30 dark:text-green-400'
                            : 'bg-gray-50 border-gray-200 text-gray-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-400'
                    }`}>
                        <span className={`w-2 h-2 rounded-full ${hasActive ? 'bg-green-500 animate-pulse' : 'bg-gray-400'}`} />
                        {hasActive ? `Đang xử lý ${counts.processing} tài liệu` : 'Không có tài liệu đang chạy'}
                    </div>

                    {!isOnline && (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-red-50 border border-red-200 text-red-600 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-400">
                            <WifiOff className="w-3 h-3" />
                            Offline
                        </div>
                    )}

                    <button
                        onClick={handleRefresh}
                        disabled={refreshing}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                    >
                        <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                        Làm mới
                    </button>
                </div>
            </div>

            {/* ── Thống kê: một thẻ cho mỗi trạng thái, bấm để lọc ── */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 px-2">
                {STATUS_FILTERS.map(({ key, state }) => (
                    <StateStatCard
                        key={key}
                        state={state}
                        count={counts[key] ?? 0}
                        isActive={activeFilter === key}
                        onClick={() => handleFilterChange(key)}
                    />
                ))}
            </div>

            {/* ── Danh sách tài liệu ── */}
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden mx-2 shadow-sm">
                <div className="px-6 pt-4 pb-0 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
                    <div className="flex items-center gap-1 flex-wrap">
                        {STATUS_FILTERS.map(({ key, state }) => {
                            const TabIcon = state.icon;
                            const isActive = activeFilter === key;
                            return (
                                <button
                                    key={key}
                                    onClick={() => handleFilterChange(key)}
                                    className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold rounded-t-lg border-b-2 transition-all ${
                                        isActive
                                            ? `border-current ${state.text}`
                                            : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                                    }`}
                                >
                                    <TabIcon className="w-3.5 h-3.5" />
                                    {state.label}
                                    <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold border ${
                                        isActive ? state.badge : 'bg-gray-100 text-gray-500 border-transparent dark:bg-gray-800 dark:text-gray-400'
                                    }`}>
                                        {counts[key] ?? 0}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                    <span className="text-xs text-gray-400 pb-2">{docs.length} tài liệu</span>
                </div>

                {/* Mô tả trạng thái đang xem — để người dùng biết tab này nghĩa là gì */}
                {activeState && (
                    <p className="px-6 py-2.5 text-xs text-gray-500 dark:text-gray-400 bg-gray-50/70 dark:bg-gray-800/40 border-b border-gray-100 dark:border-gray-800">
                        {activeState.description}
                    </p>
                )}

                {loading ? (
                    <div className="flex items-center justify-center py-16">
                        <Loader2 className="w-8 h-8 text-primary-600 animate-spin" />
                    </div>
                ) : docs.length === 0 ? (
                    <div className="py-16 text-center">
                        <div className={`w-16 h-16 rounded-2xl ${activeState?.iconWrap || 'bg-gray-100 dark:bg-gray-800'} flex items-center justify-center mx-auto mb-4`}>
                            {activeState && <activeState.icon className={`w-8 h-8 ${activeState.iconColor}`} />}
                        </div>
                        <p className="text-base font-semibold text-gray-500 dark:text-gray-400">
                            Không có tài liệu ở trạng thái "{activeState?.label}"
                        </p>
                        <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                            Chọn một trạng thái khác để xem các tài liệu còn lại
                        </p>
                    </div>
                ) : (
                    <div className="divide-y divide-gray-50 dark:divide-gray-800">
                        {docs.map((doc) => (
                            <DocumentStatusRow key={doc.id} doc={doc} />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
