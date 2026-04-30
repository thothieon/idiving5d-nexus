import { Injectable, signal } from '@angular/core';
import { StaffPermissions } from '../api/models';

const KEY_TOKEN       = 'ADMIN_TOKEN';
const KEY_ROLE        = 'ADMIN_ROLE';
const KEY_NAME        = 'ADMIN_NAME';
const KEY_PERMISSIONS = 'ADMIN_PERMISSIONS';

@Injectable({ providedIn: 'root' })
export class AdminTokenService {
  private _token       = signal<string>(localStorage.getItem(KEY_TOKEN) ?? '');
  private _role        = signal<string>(localStorage.getItem(KEY_ROLE)  ?? '');
  private _name        = signal<string>(localStorage.getItem(KEY_NAME)  ?? '');
  private _permissions = signal<StaffPermissions | null>(
    JSON.parse(localStorage.getItem(KEY_PERMISSIONS) ?? 'null')
  );

  get(): string | null { return localStorage.getItem(KEY_TOKEN); }

  token()       { return this._token(); }
  role()        { return this._role(); }
  name()        { return this._name(); }
  permissions() { return this._permissions(); }
  has()         { return !!this._token(); }
  isAdmin()     { return this._role() === 'admin'; }

  /** 檢查是否有特定功能權限。admin 無條件通過；客服依 permissions 物件判斷 */
  can(key: keyof StaffPermissions): boolean {
    if (this._role() === 'admin') return true;
    const perms = this._permissions();
    if (perms === null) return false;  // 未設定權限的客服帳號 → 無存取
    return perms[key] === true;
  }

  /** 僅更新 permissions（不影響 token/role/name），供自動同步使用 */
  updatePermissions(permissions: StaffPermissions | null) {
    const val = permissions ?? null;
    localStorage.setItem(KEY_PERMISSIONS, JSON.stringify(val));
    this._permissions.set(val);
  }

  set(token: string, role = '', name = '', permissions: StaffPermissions | null = null) {
    const t = (token ?? '').trim();
    localStorage.setItem(KEY_TOKEN,       t);
    localStorage.setItem(KEY_ROLE,        role);
    localStorage.setItem(KEY_NAME,        name);
    localStorage.setItem(KEY_PERMISSIONS, JSON.stringify(permissions));
    this._token.set(t);
    this._role.set(role);
    this._name.set(name);
    this._permissions.set(permissions);
  }

  clear() {
    localStorage.removeItem(KEY_TOKEN);
    localStorage.removeItem(KEY_ROLE);
    localStorage.removeItem(KEY_NAME);
    localStorage.removeItem(KEY_PERMISSIONS);
    this._token.set('');
    this._role.set('');
    this._name.set('');
    this._permissions.set(null);
  }
}
