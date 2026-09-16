import { Loader2 } from 'lucide-react';
import {
    DOCUMENT_STATES,
    PIPELINE_STEPS,
    getPipelineStepLabel,
    resolveDocumentState,
} from '../../utils/documentStatus';

/**
 * ProcessingProgressBar — tiến trình xử lý tài liệu sau khi được duyệt.
 * Dùng chung cho Approvals, Documents, DocumentView và Tiến trình xử lý.
 *
 * Nhãn và màu lấy từ utils/documentStatus.js để mọi trang nói cùng một ngôn ngữ.
 *
 * Props:
 *   status       — 'parsing' | 'processing' | 'indexing' | 'indexed' | 'failed'
 *   chunkCount   — number (optional)
 *   errorMessage — string (optional)
 *   compact      — boolean: render nhỏ gọn hơn khi nằm trong danh sách
 */
export default function ProcessingProgressBar({ status, chunkCount, errorMessage, compact = false }) {
    const state = resolveDocumentState({ status, approval_status: 'approved' });
    const isDone = state === DOCUMENT_STATES.indexed;
    const isFailed = state === DOCUMENT_STATES.failed;
    const currentStepIdx = PIPELINE_STEPS.findIndex(
        (s) => s.key === String(status || '').toLowerCase()
    );
    const StateIcon = state.icon;

    const dotSize = compact ? 'w-4 h-4' : 'w-5 h-5';
    const dotIconSize = compact ? 'w-2.5 h-2.5' : 'w-3 h-3';
    const labelIconSize = compact ? 'w-3 h-3' : 'w-3.5 h-3.5';

    return (
        <div className={`flex items-center gap-3 ${compact ? 'mt-1' : 'mt-2'}`}>
            {/* Các bước pipeline */}
            <div className="flex items-center gap-1">
                {PIPELINE_STEPS.map((step, i) => {
                    const isActive = i === currentStepIdx;
                    const isPast = isDone || (currentStepIdx > -1 && i < currentStepIdx);
                    const StepIcon = step.icon;
                    // Tài liệu lỗi không còn bước "đang chạy" — đánh dấu đỏ ở bước
                    // đầu để thấy ngay tiến trình đã dừng giữa chừng.
                    const failedMarker = isFailed && currentStepIdx === -1 && i === 0;
                    return (
                        <div key={step.key} className="flex items-center gap-1" title={step.label}>
                            <div
                                className={`${dotSize} rounded-full flex items-center justify-center flex-shrink-0 ${
                                    isFailed && (isActive || failedMarker)
                                        ? 'bg-red-500'
                                        : isDone
                                        ? 'bg-emerald-500'
                                        : isPast || isActive
                                        ? 'bg-primary-500'
                                        : 'bg-gray-200 dark:bg-gray-700'
                                }`}
                            >
                                <StepIcon
                                    className={`${dotIconSize} ${
                                        isDone || isPast || isActive || failedMarker
                                            ? 'text-white'
                                            : 'text-gray-400'
                                    } ${isActive && !isFailed && !isDone ? 'animate-spin' : ''}`}
                                />
                            </div>
                            {i < PIPELINE_STEPS.length - 1 && (
                                <div
                                    className={`${compact ? 'w-3' : 'w-4'} h-0.5 ${
                                        isPast || isDone ? 'bg-primary-400' : 'bg-gray-200 dark:bg-gray-700'
                                    }`}
                                />
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Nhãn trạng thái */}
            <div className="flex items-center gap-1.5 min-w-0">
                {isDone || isFailed ? (
                    <StateIcon className={`${labelIconSize} ${state.iconColor} flex-shrink-0`} />
                ) : (
                    <Loader2 className={`${labelIconSize} text-primary-500 animate-spin flex-shrink-0`} />
                )}
                <span className={`${compact ? 'text-[10px]' : 'text-xs'} font-medium truncate ${state.text}`}>
                    {isDone
                        ? `${state.label}${chunkCount ? ` · ${chunkCount} chunks` : ''}`
                        : isFailed
                        ? `${state.label}: ${errorMessage || 'Xử lý thất bại'}`
                        : `${getPipelineStepLabel(status)}${chunkCount > 0 ? ` · ${chunkCount} chunks` : ''}`}
                </span>
            </div>
        </div>
    );
}
