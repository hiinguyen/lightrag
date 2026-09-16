import { useRef, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { File, Eye, Download, Share2, Trash2, MoreHorizontal } from 'lucide-react';
import { fileTypeIconMap, fileTypeColors, fileTypeBgColors } from './fileTypes';
import { getExt, formatBytes, formatDate, getInitials, avatarColor, categoryColors, getCategoryLabel } from '../../utils/formatters';
import ProcessingProgressBar from '../shared/ProcessingProgressBar';
import {
    DOCUMENT_STATES,
    resolveDocumentState,
    getApprovalStageLabel,
} from '../../utils/documentStatus';

function DropdownMenu({ anchorEl, onClose, children }) {
    const menuRef = useRef(null);
    const [style, setStyle] = useState({ opacity: 0 });

    useEffect(() => {
        if (!anchorEl) return;

        const rect = anchorEl.getBoundingClientRect();
        const MENU_WIDTH = 176; // w-44 = 11rem = 176px
        const MENU_HEIGHT = 180; // approximate

        const viewportW = window.innerWidth;
        const viewportH = window.innerHeight;

        // Position to the right of the button by default; shift left if it overflows
        let left = rect.right - MENU_WIDTH;
        if (left < 8) left = 8;
        if (left + MENU_WIDTH > viewportW - 8) left = viewportW - MENU_WIDTH - 8;

        // Position below the button; flip up if not enough room
        let top = rect.bottom + 4;
        if (top + MENU_HEIGHT > viewportH - 8) top = rect.top - MENU_HEIGHT - 4;

        setStyle({ top, left, opacity: 1 });
    }, [anchorEl]);

    // Close on outside click
    useEffect(() => {
        const handler = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target) &&
                anchorEl && !anchorEl.contains(e.target)) {
                onClose();
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [anchorEl, onClose]);

    return createPortal(
        <div
            ref={menuRef}
            style={{ position: 'fixed', zIndex: 9999, width: 176, ...style }}
            className="bg-white dark:bg-gray-900 rounded-xl shadow-xl border border-gray-100 dark:border-gray-800 py-1 animate-fade-in"
            onClick={e => e.stopPropagation()}
        >
            {children}
        </div>,
        document.body
    );
}

export default function DocumentRow({ doc, openMenu, onToggleMenu, onView, onDownload, onDelete, renderAsTableCells, processingStatus }) {
    const ext = doc.type || getExt(doc.name);
    const Icon = fileTypeIconMap[ext] || File;
    const iconColor = fileTypeColors[ext] || 'text-gray-500';
    const bgColor = fileTypeBgColors[ext] || 'bg-gray-100 dark:bg-gray-800';
    const catLabel = getCategoryLabel(doc.category);
    const catColor = categoryColors[catLabel] || categoryColors['Khác'];
    const [thumbFailed, setThumbFailed] = useState(false);
    const tags = Array.isArray(doc.tags)
        ? doc.tags.filter(Boolean)
        : typeof doc.tags === 'string'
        ? doc.tags.split(',').map(t => t.trim()).filter(Boolean)
        : [];

    const btnRef = useRef(null);
    const isOpen = openMenu === doc.id;

    // Effective processing status: prefer live-polled data, fall back to doc field
    const liveStatus = processingStatus?.status || doc.status;
    const state = resolveDocumentState({ ...doc, status: liveStatus });
    // Thanh tiến trình chỉ có nghĩa khi tài liệu đã vào pipeline và ta có dữ liệu
    // poll; các trạng thái còn lại (chờ duyệt, lỗi, từ chối) dùng badge trạng thái.
    const showProgressBar =
        Boolean(processingStatus) &&
        (state === DOCUMENT_STATES.processing || state === DOCUMENT_STATES.indexed);
    const StateIcon = state.icon;

    const cells = (
        <>
            {/* Name */}
            <td className="px-6 py-4">
                <div className="flex items-center gap-3">
                    <div className={`w-9 h-9 rounded-lg ${bgColor} flex items-center justify-center flex-shrink-0`}>
                        {doc.thumbnail && !thumbFailed ? (
                            <img
                                src={`${import.meta.env.VITE_API_BASE_URL || ''}/api/documents/${doc.id}/thumbnail`}
                                alt={doc.name}
                                className="w-full h-full object-cover rounded-lg"
                                onError={() => setThumbFailed(true)}
                            />
                        ) : (
                            <Icon className={`w-4.5 h-4.5 ${iconColor}`} />
                        )}
                    </div>
                    <div className="min-w-0">
                        <span className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-[160px] lg:max-w-xs block" title={doc.name}>
                            {doc.name}
                        </span>
                        {tags.length > 0 && (
                            <div className="flex items-center gap-1.5 mt-1 flex-wrap max-w-xs lg:max-w-md">
                                {tags.slice(0, 3).map((tag) => (
                                    <span
                                        key={`${doc.id}-${tag}`}
                                        className="px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
                                    >
                                        #{tag}
                                    </span>
                                ))}
                                {tags.length > 3 && (
                                    <span className="text-[10px] text-gray-400">+{tags.length - 3}</span>
                                )}
                            </div>
                        )}
                        {showProgressBar ? (
                            <ProcessingProgressBar
                                status={processingStatus.status}
                                chunkCount={processingStatus.chunk_count}
                                compact
                            />
                        ) : (
                            <span className={`inline-flex items-center gap-1 mt-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${state.badge}`}>
                                <StateIcon className={`w-3 h-3 ${state.spin ? 'animate-spin' : ''}`} />
                                {state === DOCUMENT_STATES.awaiting_approval
                                    ? getApprovalStageLabel(doc.approval_status)
                                    : state.shortLabel}
                            </span>
                        )}
                        {state === DOCUMENT_STATES.failed && (
                            <p className="text-[11px] text-red-500 dark:text-red-400/80 mt-1 line-clamp-2 max-w-md" title={processingStatus?.error_message || doc.error_message || ''}>
                                {processingStatus?.error_message || doc.error_message || 'Xử lý thất bại.'}
                            </p>
                        )}
                    </div>
                </div>
            </td>
            {/* Category */}
            <td className="px-6 py-4 hidden sm:table-cell">
                <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${catColor}`}>
                    {catLabel}
                </span>
            </td>
            {/* Date Modified */}
            <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400 hidden md:table-cell">
                {formatDate(doc.date || doc.created_at)}
            </td>
            {/* Size */}
            <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400 hidden md:table-cell">
                {formatBytes(doc.size)}
            </td>
            {/* Owner */}
            <td className="px-6 py-4 hidden lg:table-cell">
                <div className="flex items-center gap-2.5">
                    <div className={`w-7 h-7 rounded-full ${avatarColor(doc.owner)} flex items-center justify-center text-white text-xs font-semibold flex-shrink-0`}>
                        {getInitials(doc.owner)}
                    </div>
                    <span className="text-sm text-gray-700 dark:text-gray-300">{doc.owner || '—'}</span>
                </div>
            </td>
            {/* Actions — three-dot menu */}
            <td className="px-6 py-4 text-right">
                <button
                    ref={btnRef}
                    onClick={(e) => { e.stopPropagation(); onToggleMenu(doc.id); }}
                    className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                >
                    <MoreHorizontal className="w-4 h-4" />
                </button>

                {isOpen && (
                    <DropdownMenu anchorEl={btnRef.current} onClose={() => onToggleMenu(null)}>
                        <button onClick={() => { onView(doc); onToggleMenu(null); }} className="flex items-center gap-2.5 w-full px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                            <Eye className="w-4 h-4 text-gray-400" /> Xem
                        </button>
                        <button onClick={() => { onDownload(doc); onToggleMenu(null); }} className="flex items-center gap-2.5 w-full px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                            <Download className="w-4 h-4 text-gray-400" /> Tải xuống
                        </button>
                        <button className="flex items-center gap-2.5 w-full px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                            <Share2 className="w-4 h-4 text-gray-400" /> Chia sẻ
                        </button>
                        <div className="my-1 border-t border-gray-100 dark:border-gray-800" />
                        <button onClick={() => { onDelete(doc.id); onToggleMenu(null); }} className="flex items-center gap-2.5 w-full px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors">
                            <Trash2 className="w-4 h-4" /> Xóa
                        </button>
                    </DropdownMenu>
                )}
            </td>
        </>
    );

    if (renderAsTableCells) return cells;

    return (
        <tr className="hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors">
            {cells}
        </tr>
    );
}
