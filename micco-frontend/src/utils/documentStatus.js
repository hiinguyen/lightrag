import { Clock, FileSearch, Loader2, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

/**
 * Nguồn duy nhất mô tả trạng thái của một tài liệu trong UI.
 *
 * Backend giữ hai trường tách rời — `status` (vòng đời xử lý) và
 * `approval_status` (vòng đời phê duyệt) — nhưng người dùng chỉ cần thấy MỘT
 * trạng thái. `resolveDocumentState()` gộp hai trường đó lại, và mọi màn hình
 * (Tiến trình xử lý, Tài liệu, Chi tiết, Tổng quan) đều lấy nhãn/màu từ đây để
 * cùng một tài liệu không bao giờ hiển thị khác nhau giữa các trang.
 */

export const DOCUMENT_STATES = {
    awaiting_approval: {
        key: 'awaiting_approval',
        label: 'Chờ phê duyệt',
        shortLabel: 'Chờ duyệt',
        description: 'Tài liệu đang đợi người có thẩm quyền phê duyệt trước khi xử lý',
        icon: Clock,
        text: 'text-amber-600 dark:text-amber-400',
        badge: 'text-amber-700 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-500/10 dark:border-amber-500/30',
        iconWrap: 'bg-amber-100 dark:bg-amber-500/20',
        iconColor: 'text-amber-600 dark:text-amber-400',
        dot: 'bg-amber-500',
        spin: false,
    },
    processing: {
        key: 'processing',
        label: 'Đang xử lý',
        shortLabel: 'Đang xử lý',
        description: 'Hệ thống đang phân tích, tách chunk và lập chỉ mục tài liệu',
        icon: Loader2,
        text: 'text-primary-600 dark:text-primary-400',
        badge: 'text-primary-700 bg-primary-50 border-primary-200 dark:text-primary-300 dark:bg-primary-500/10 dark:border-primary-500/30',
        iconWrap: 'bg-primary-100 dark:bg-primary-500/20',
        iconColor: 'text-primary-600 dark:text-primary-400',
        dot: 'bg-primary-500',
        spin: true,
    },
    failed: {
        key: 'failed',
        label: 'Xử lý lỗi',
        shortLabel: 'Xử lý lỗi',
        description: 'Xử lý thất bại — tài liệu đã được trả về hàng đợi phê duyệt để thử lại',
        icon: AlertTriangle,
        text: 'text-red-600 dark:text-red-400',
        badge: 'text-red-700 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-500/10 dark:border-red-500/30',
        iconWrap: 'bg-red-100 dark:bg-red-500/20',
        iconColor: 'text-red-600 dark:text-red-400',
        dot: 'bg-red-500',
        spin: false,
    },
    indexed: {
        key: 'indexed',
        label: 'Hoàn tất',
        shortLabel: 'Hoàn tất',
        description: 'Tài liệu đã được lập chỉ mục và sẵn sàng sử dụng',
        icon: CheckCircle2,
        text: 'text-emerald-600 dark:text-emerald-400',
        badge: 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-500/10 dark:border-emerald-500/30',
        iconWrap: 'bg-emerald-100 dark:bg-emerald-500/20',
        iconColor: 'text-emerald-600 dark:text-emerald-400',
        dot: 'bg-emerald-500',
        spin: false,
    },
    rejected: {
        key: 'rejected',
        label: 'Bị từ chối',
        shortLabel: 'Từ chối',
        description: 'Tài liệu đã bị từ chối và không được đưa vào hệ thống',
        icon: XCircle,
        text: 'text-gray-500 dark:text-gray-400',
        badge: 'text-gray-600 bg-gray-100 border-gray-200 dark:text-gray-400 dark:bg-gray-700/50 dark:border-gray-600',
        iconWrap: 'bg-gray-100 dark:bg-gray-800',
        iconColor: 'text-gray-500 dark:text-gray-400',
        dot: 'bg-gray-400',
        spin: false,
    },
};

const IN_PIPELINE_STATUSES = ['parsing', 'processing', 'indexing'];

/**
 * Gộp `status` + `approval_status` thành một trạng thái hiển thị duy nhất.
 *
 * Thứ tự ưu tiên có chủ đích: `failed` được kiểm tra TRƯỚC `approval_status`,
 * vì tài liệu lỗi sẽ quay lại hàng đợi phê duyệt (xem
 * app/services/document_failure.py) — nếu xét phê duyệt trước thì một tài liệu
 * lỗi sẽ bị hiển thị nhầm thành "Chờ duyệt" và không ai biết nó đã hỏng.
 */
export function resolveDocumentState(doc) {
    const status = String(doc?.status || '').toLowerCase();
    const approvalStatus = String(doc?.approval_status || '').toLowerCase();

    if (status === 'failed') return DOCUMENT_STATES.failed;
    if (status === 'rejected' || approvalStatus === 'rejected') return DOCUMENT_STATES.rejected;
    if (status === 'indexed') return DOCUMENT_STATES.indexed;
    if (IN_PIPELINE_STATUSES.includes(status)) return DOCUMENT_STATES.processing;
    return DOCUMENT_STATES.awaiting_approval;
}

/** Nhãn chi tiết hơn cho tài liệu đang chờ duyệt (cấp phòng vs cấp tổ chức). */
export function getApprovalStageLabel(approvalStatus) {
    if (approvalStatus === 'pending_org') return 'Chờ duyệt cấp tổ chức';
    if (approvalStatus === 'pending' || approvalStatus === 'pending_dept') return 'Chờ duyệt cấp phòng';
    return DOCUMENT_STATES.awaiting_approval.label;
}

/** Các bước tiến trình sau khi tài liệu được duyệt. */
export const PIPELINE_STEPS = [
    { key: 'parsing', label: 'Đang phân tích', icon: FileSearch },
    { key: 'processing', label: 'Đang xử lý', icon: Loader2 },
    { key: 'indexing', label: 'Đang lập chỉ mục', icon: Loader2 },
    { key: 'indexed', label: 'Hoàn tất', icon: CheckCircle2 },
];

/** Nhãn cho bước hiện tại trong pipeline (chi tiết hơn nhãn trạng thái chung). */
export function getPipelineStepLabel(status) {
    const step = PIPELINE_STEPS.find((s) => s.key === String(status || '').toLowerCase());
    return step?.label || DOCUMENT_STATES.processing.label;
}
