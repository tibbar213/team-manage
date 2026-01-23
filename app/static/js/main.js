/**
 * GPT Team 管理系统 - 通用 JavaScript
 */

// Toast 提示函数
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    if (!toast) return;

    let icon = 'info';
    if (type === 'success') icon = 'check-circle';
    if (type === 'error') icon = 'alert-circle';

    toast.innerHTML = `<i data-lucide="${icon}"></i><span>${message}</span>`;
    toast.className = `toast ${type} show`;

    if (window.lucide) {
        lucide.createIcons();
    }

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// 日期格式化函数
function formatDateTime(dateString) {
    if (!dateString) return '-';

    const date = new Date(dateString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${year}-${month}-${day} ${hours}:${minutes}`;
}

// 登出函数
async function logout() {
    if (!confirm('确定要登出吗?')) {
        return;
    }

    try {
        const response = await fetch('/auth/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (response.ok && data.success) {
            window.location.href = '/login';
        } else {
            showToast('登出失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    }
}

// API 调用封装
async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || data.detail || '请求失败');
        }

        return { success: true, data };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

// 确认对话框
function confirmAction(message) {
    return confirm(message);
}

// 页面加载完成后执行
document.addEventListener('DOMContentLoaded', function () {
    // 检查认证状态
    checkAuthStatus();
});

// 检查认证状态
async function checkAuthStatus() {
    // 如果在登录页面,跳过检查
    if (window.location.pathname === '/login') {
        return;
    }

    try {
        const response = await fetch('/auth/status');
        const data = await response.json();

        if (!data.authenticated && window.location.pathname.startsWith('/admin')) {
            // 未登录且在管理员页面,跳转到登录页
            window.location.href = '/login';
        }
    } catch (error) {
        console.error('检查认证状态失败:', error);
    }
}

// === 模态框控制逻辑 ===

function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden'; // 防止背景滚动
    }
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        document.body.style.overflow = '';
    }
}

function switchModalTab(modalId, tabId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    // 切换按钮状态
    const tabs = modal.querySelectorAll('.modal-tab-btn');
    tabs.forEach(tab => {
        if (tab.getAttribute('onclick').includes(`'${tabId}'`)) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });

    // 切换面板显示
    const panels = modal.querySelectorAll('.import-panel, .card-body');
    panels.forEach(panel => {
        if (panel.id === tabId) {
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    });
}

// === Team 导入逻辑 ===

async function handleSingleImport(event) {
    event.preventDefault();
    const form = event.target;
    const accessToken = form.accessToken.value.trim();
    const email = form.email.value.trim();
    const accountId = form.accountId.value.trim();
    const submitButton = form.querySelector('button[type="submit"]');

    submitButton.disabled = true;
    submitButton.textContent = '导入中...';

    try {
        const result = await apiCall('/admin/teams/import', {
            method: 'POST',
            body: JSON.stringify({
                import_type: 'single',
                access_token: accessToken,
                email: email || null,
                account_id: accountId || null
            })
        });

        if (result.success) {
            showToast('Team 导入成功！', 'success');
            form.reset();
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(result.error || '导入失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = '导入';
    }
}

async function handleBatchImport(event) {
    event.preventDefault();
    const form = event.target;
    const batchContent = form.batchContent.value.trim();
    const submitButton = form.querySelector('button[type="submit"]');
    const resultsContainer = document.getElementById('batchResultsContainer');
    const resultsDiv = document.getElementById('batchResults');

    submitButton.disabled = true;
    submitButton.textContent = '导入中...';

    try {
        const result = await apiCall('/admin/teams/import', {
            method: 'POST',
            body: JSON.stringify({
                import_type: 'batch',
                content: batchContent
            })
        });

        if (result.success) {
            const data = result.data;
            let html = `<div class="batch-summary">
                <p>总数: ${data.total} | 成功: <span class="text-success">${data.success_count}</span> | 失败: <span class="text-danger">${data.failed_count}</span></p>
            </div>`;

            if (data.results && data.results.length > 0) {
                html += '<div class="batch-results"><table class="data-table"><thead><tr><th>邮箱</th><th>状态</th><th>消息</th></tr></thead><tbody>';
                data.results.forEach(res => {
                    const statusClass = res.success ? 'text-success' : 'text-danger';
                    const statusText = res.success ? '成功' : '失败';
                    html += `<tr>
                        <td>${res.email}</td>
                        <td class="${statusClass}">${statusText}</td>
                        <td>${res.success ? res.message : res.error}</td>
                    </tr>`;
                });
                html += '</tbody></table></div>';
            }

            resultsDiv.innerHTML = html;
            resultsContainer.style.display = 'block';

            if (data.failed_count === 0) {
                showToast('全部导入成功！', 'success');
                setTimeout(() => location.reload(), 2000);
            }
        } else {
            showToast(result.error || '批量导入失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = '批量导入';
    }
}

// === 兑换码生成逻辑 ===

async function generateSingle(event) {
    event.preventDefault();
    const form = event.target;
    const customCode = form.customCode.value.trim();
    const expiresDays = form.expiresDays.value;

    const data = { type: 'single' };
    if (customCode) data.code = customCode;
    if (expiresDays) data.expires_days = parseInt(expiresDays);

    const result = await apiCall('/admin/codes/generate', {
        method: 'POST',
        body: JSON.stringify(data)
    });

    if (result.success) {
        document.getElementById('generatedCode').textContent = result.data.code;
        document.getElementById('singleResult').style.display = 'block';
        form.reset();
        showToast('兑换码生成成功', 'success');
        // 如果在列表中，延迟刷新
        if (window.location.pathname === '/admin/codes') {
            setTimeout(() => location.reload(), 2000);
        }
    } else {
        showToast(result.error || '生成失败', 'error');
    }
}

async function generateBatch(event) {
    event.preventDefault();
    const form = event.target;
    const count = parseInt(form.count.value);
    const expiresDays = form.expiresDays.value;

    if (count < 1 || count > 1000) {
        showToast('生成数量必须在1-1000之间', 'error');
        return;
    }

    const data = { type: 'batch', count: count };
    if (expiresDays) data.expires_days = parseInt(expiresDays);

    const result = await apiCall('/admin/codes/generate', {
        method: 'POST',
        body: JSON.stringify(data)
    });

    if (result.success) {
        document.getElementById('batchTotal').textContent = result.data.total;
        document.getElementById('batchCodes').value = result.data.codes.join('\n');
        document.getElementById('batchResult').style.display = 'block';
        form.reset();
        showToast(`成功生成 ${result.data.total} 个兑换码`, 'success');
        if (window.location.pathname === '/admin/codes') {
            setTimeout(() => location.reload(), 3000);
        }
    } else {
        showToast(result.error || '生成失败', 'error');
    }
}

// 统一复制到剪贴板函数
async function copyToClipboard(text) {
    if (!text) return;

    try {
        // 尝试使用 Modern Clipboard API
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            showToast('已复制到剪贴板', 'success');
            return true;
        }
    } catch (err) {
        console.error('Modern copy failed:', err);
    }

    // Fallback: 使用 textarea 方式
    try {
        const textArea = document.createElement("textarea");
        textArea.value = text;

        // 确保 textarea 不可见且不影响布局
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);

        textArea.focus();
        textArea.select();

        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);

        if (successful) {
            showToast('已复制到剪贴板', 'success');
            return true;
        }
    } catch (err) {
        console.error('Fallback copy failed:', err);
    }

    showToast('复制失败', 'error');
    return false;
}

// === 辅助函数 ===

function copyCode(code) {
    // 如果没有传入 code，尝试从生成结果中获取
    if (!code) {
        const generatedCodeEl = document.getElementById('generatedCode');
        code = generatedCodeEl ? generatedCodeEl.textContent : '';
    }

    if (code) {
        copyToClipboard(code);
    } else {
        showToast('无内容可复制', 'error');
    }
}

function copyBatchCodes() {
    const codes = document.getElementById('batchCodes').value;
    copyToClipboard(codes);
}

function downloadCodes() {
    const codes = document.getElementById('batchCodes').value;
    const blob = new Blob([codes], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `redemption_codes_${new Date().getTime()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('下载成功', 'success');
}
// === 成员管理逻辑 ===

async function viewMembers(teamId, teamEmail = '') {
    window.currentTeamId = teamId;
    const modal = document.getElementById('manageMembersModal');
    if (!modal) return;

    // 设置基本信息
    document.getElementById('modalTeamEmail').textContent = teamEmail;

    // 打开模态框
    showModal('manageMembersModal');

    // 加载成员列表
    await loadModalMemberList(teamId);
}

async function loadModalMemberList(teamId) {
    const tableBody = document.getElementById('modalMembersTableBody');
    tableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">加载中...</td></tr>';

    try {
        const result = await apiCall(`/admin/teams/${teamId}/members/list`);
        if (result.success) {
            const members = result.data.members;
            if (members.length === 0) {
                tableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 2rem;">暂无成员</td></tr>';
            } else {
                tableBody.innerHTML = members.map(m => `
                    <tr>
                        <td>${m.email}</td>
                        <td>
                            <span class="role-badge role-${m.role}">
                                ${m.role === 'account-owner' ? '所有者' : '成员'}
                            </span>
                        </td>
                        <td>${formatDateTime(m.added_at)}</td>
                        <td style="text-align: right;">
                            ${m.role !== 'account-owner' ? `
                                <button onclick="deleteMember('${teamId}', '${m.user_id}', '${m.email}', true)" class="btn btn-sm btn-danger">
                                    <i data-lucide="trash-2"></i> 删除
                                </button>
                            ` : '<span class="text-muted">不可删除</span>'}
                        </td>
                    </tr>
                `).join('');
                if (window.lucide) lucide.createIcons();
            }
        } else {
            tableBody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--danger);">${result.error}</td></tr>`;
        }
    } catch (error) {
        tableBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--danger);">加载失败</td></tr>';
    }
}

async function handleAddMember(event) {
    event.preventDefault();
    const form = event.target;
    const email = form.email.value.trim();
    const submitButton = document.getElementById('addMemberSubmitBtn');
    const teamId = window.currentTeamId;

    if (!teamId) {
        showToast('无法获取 Team ID', 'error');
        return;
    }

    submitButton.disabled = true;
    const originalText = submitButton.innerHTML;
    submitButton.textContent = '添加中...';

    try {
        const result = await apiCall(`/admin/teams/${teamId}/members/add`, {
            method: 'POST',
            body: JSON.stringify({ email })
        });

        if (result.success) {
            showToast('成员添加成功！', 'success');
            form.reset();
            // 在模态框模式下，只负载列表
            if (document.getElementById('manageMembersModal').classList.contains('show')) {
                await loadModalMemberList(teamId);
            } else {
                setTimeout(() => location.reload(), 1500);
            }
        } else {
            showToast(result.error || '添加失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.innerHTML = originalText;
    }
}

async function deleteMember(teamId, userId, email, inModal = false) {
    if (!confirm(`确定要删除成员 "${email}" 吗?\n\n此操作不可恢复!`)) {
        return;
    }

    try {
        showToast('正在删除...', 'info');
        const result = await apiCall(`/admin/teams/${teamId}/members/${userId}/delete`, {
            method: 'POST'
        });

        if (result.success) {
            showToast('删除成功', 'success');
            if (inModal) {
                await loadModalMemberList(teamId);
            } else {
                setTimeout(() => location.reload(), 1000);
            }
        } else {
            showToast(result.error || '删除失败', 'error');
        }
    } catch (error) {
        showToast('网络错误', 'error');
    }
}
