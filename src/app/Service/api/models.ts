// models.ts

// ── 舊有（保留相容）─────────────────────────────────────────
export type TicketStatus = 'open' | 'pending' | 'closed';

export interface StaffPermissions {
  can_registration?: boolean;
  can_customers?:    boolean;
  can_courses?:      boolean;
  can_pagestats?:    boolean;
  can_linestats?:    boolean;
  can_questions?:    boolean;
  can_quickreply?:   boolean;
}

export interface StaffItem {
  id:          number;
  name:        string;
  username:    string | null;
  email:       string | null;
  role:        'admin' | 'staff';
  permissions: StaffPermissions | null;
  is_active:   number;
  created_at:  string;
}

export interface Dashboard {
  today_new:   number;
  open_cnt:    number;
  pending_cnt: number;
  overdue_60m: number;
}

export interface TicketListItem {
  ticket_id:                  number;
  status:                     TicketStatus;
  current_status:             SessionStatus;
  status_label:               string;
  priority:                   string;
  subject:                    string | null;
  last_in_text:               string | null;
  last_customer_text:         string | null;
  last_text:                  string | null;   // 後端實際回傳欄位
  channel_type:               string;
  updated_at:                 string;
  last_customer_message_at:   string | null;
  minutes_since_last_message: number | null;
  is_overdue:                 boolean;
  customer_name:              string | null;
  display_name:               string | null;
  picture_url:                string | null;
  phone:                      string | null;
  active_agent:               string | null;
  customer_id:                number | null;
  tags?:                      Tag[];
}

export interface TicketMessage {
  id:                    number;
  direction:             'in' | 'out';
  message_type:          'text' | 'image' | 'video' | 'audio' | 'file' | 'sticker' | string;
  text:                  string | null;
  content_url:           string | null;
  content_path:          string | null;
  content_name:          string | null;
  content_mime:          string | null;
  sticker_id:            string | null;
  package_id:            string | null;
  sticker_resource_type: string | null;
  sticker_url:           string | null;
  sender_type:           'customer' | 'staff' | null;
  sender_name:           string | null;
  sender_picture_url:    string | null;
  staff_id:              number | null;
  line_message_id:       string | null;
  created_at:            string;
}

// ── 狀態機（新增）────────────────────────────────────────────
export type SessionStatus =
  | 'new' | 'waiting' | 'in_progress'
  | 'collecting' | 'booking' | 'closed';

export const SESSION_STATUS_LABEL: Record<SessionStatus, string> = {
  new:         '新訊息',
  waiting:     '等待客服',
  in_progress: '服務中',
  collecting:  '資料收集中',
  booking:     '報名/預約中',
  closed:      '已結案',
};

export const SESSION_STATUS_COLOR: Record<SessionStatus, string> = {
  new:         '#E53935',
  waiting:     '#FB8C00',
  in_progress: '#1E88E5',
  collecting:  '#8E24AA',
  booking:     '#00897B',
  closed:      '#9E9E9E',
};

export interface AllowedNext {
  status: SessionStatus;
  label:  string;
}

export interface TicketStatusResponse {
  current:       SessionStatus;
  current_label: string;
  allowed_next:  AllowedNext[];
}

export interface SessionHistory {
  id:           number;
  status:       SessionStatus;
  status_label: string;
  triggered_by: 'customer' | 'staff' | 'system';
  staff_name:   string | null;
  note:         string | null;
  created_at:   string;
}

// ── 報名（新增）──────────────────────────────────────────────
export interface Booking {
  id:           number | null;
  ticket_id:    number;
  customer_id:  number | null;
  name:         string | null;
  phone:        string | null;
  email:        string | null;
  course_item:  string | null;
  booking_date: string | null;
  booking_note: string | null;
  status:       'draft' | 'confirmed' | 'cancelled';
  created_at:   string | null;
  updated_at:   string | null;
}

export interface BookingForm {
  name:         string;
  phone:        string;
  email:        string;
  course_item:  string;
  booking_date: string;
  note:         string;
}

// ── Quick Reply ───────────────────────────────────────────────
export interface QuickReplyButton {
  label: string;
  url:   string;
}

export interface QuickReplyRule {
  id:         number;
  keyword:    string;
  reply_text: string;
  buttons:    QuickReplyButton[];
  is_active:  boolean | number;
  created_at: string;
  updated_at: string;
}

// ── LIFF 匯款回報 ────────────────────────────────────────────
export interface LiffPendingOrder {
  id:           number;
  amount:       number;
  description:  string | null;
  atm_bank_code: string;
  atm_account:  string;
  due_date:     string | null;
  created_at:   string;
}

export interface LiffSubmitResult {
  ok:           boolean;
  match_status: 'matched' | 'unmatched';
  message:      string;
}

// ── 客戶標籤 ─────────────────────────────────────────────────
export interface Tag {
  id:    number;
  name:  string;
  color: string;
}

// ── 課程排程 ─────────────────────────────────────────────────
export interface CourseSchedule {
  id:          number;
  course_code: string;
  course_name: string;
  start_date:  string;   // YYYY-MM-DD
  end_date:    string;   // YYYY-MM-DD
  color:       string;
  note:        string | null;
  is_active:   number;
  created_at?: string;
  updated_at?: string;
}

export interface CourseScheduleForm {
  course_code: string;
  course_name: string;
  start_date:  string;
  end_date:    string;
  color:       string;
  note:        string;
  is_active:   number;
}

// ── 客戶筆記 ─────────────────────────────────────────────────
export interface CustomerNote {
  id:          number;
  customer_id: number;
  staff_id:    number | null;
  staff_name:  string | null;
  note:        string;
  created_at:  string;
  updated_at:  string;
}

// ── 報名系統 ─────────────────────────────────────────────────
export interface RegCourse {
  id:           number;
  course_code:  string;
  title:        string;
  type:         'course' | 'activity';
  require_form: number;
  is_active:    number;
}

export interface RegCourseForm {
  course_code:  string;
  title:        string;
  type:         string;
  description:  string;
  require_form: number;
  is_active:    number;
  sort_order:   number;
}

export interface RegSession {
  id:                number;
  course_id:         number;
  course_title:      string;
  label:             string;
  start_date:        string;
  end_date:          string;
  capacity:          number;
  waitlist_capacity: number;
  status:            'open' | 'closed';
  note:              string | null;
  confirmed_count:   number;
  waitlist_count:    number;
}

export interface RegSessionForm {
  course_id:         number;
  label:             string;
  start_date:        string;
  end_date:          string;
  capacity:          number;
  waitlist_capacity: number;
  status:            string;
  note:              string;
}

export interface RegRegistration {
  id:                 number;
  course_title:       string;
  course_code:        string;
  session_label:      string;
  start_date:         string;
  end_date:           string;
  // 客戶基本
  customer_id:        number;
  name:               string;
  id_number:          string;
  phone:              string;        // 行動電話
  home_phone:         string | null; // 住家電話
  email:              string | null;
  mid:                string | null;
  nickname:           string | null; // 暱稱
  name_en:            string | null; // 英文姓名
  birth_date:         string | null; // 出生日期
  nationality:        string | null; // 國籍
  blood_type:         string | null; // 血型
  // 地址與緊急
  address:            string | null;
  emergency_contact:  string | null;
  emergency_phone:    string | null;
  // 身體數值
  height:             number | null;
  weight:             number | null;
  vision_left:        number | null;
  vision_right:       number | null;
  // 會員
  payment_date:       string | null;
  membership_expiry:  string | null;
  // 報名狀態
  reg_status:         'pending' | 'data_confirmed' | 'payment_submitted' | 'confirmed' | 'cancelled' | 'waitlist';
  payment_status:     'unpaid' | 'paid';
  waitlist_position:  number | null;
  registered_at:      string;
  confirmed_at:       string | null;
  notes:              string | null;
  // 付款流程
  transfer_bank:      string | null;
  transfer_date:      string | null;
  transfer_note:      string | null;
  payment_submitted_at: string | null;
  // 健康申明
  health_form:        Record<string, boolean | string | null> | null;
}

export interface CustomerListItem {
  id:                number;
  name:              string;
  phone:             string;
  email:             string | null;
  id_number:         string;
  mid:               string | null;
  nickname:          string | null;
  birth_date:        string | null;
  membership_expiry: string | null;
  reg_count:         number;
  confirmed_count:   number;
  last_reg_at:       string | null;
}

export interface CustomerDetail {
  id:                number;
  name:              string;
  id_number:         string;
  phone:             string;
  home_phone:        string | null;
  email:             string | null;
  mid:               string | null;
  nickname:          string | null;
  name_en:           string | null;
  birth_date:        string | null;
  nationality:       string | null;
  blood_type:        string | null;
  address:           string | null;
  emergency_contact: string | null;
  emergency_phone:   string | null;
  height:            number | null;
  weight:            number | null;
  shoe_size:         number | null;
  vision_left:       number | null;
  vision_right:      number | null;
  payment_date:      string | null;
  membership_expiry: string | null;
  created_at:        string;
  updated_at:        string;
}

export interface CustomerRegHistory {
  id:              number;
  reg_status:      string;
  payment_status:  string;
  registered_at:   string;
  confirmed_at:    string | null;
  transfer_bank:   string | null;
  transfer_date:   string | null;
  waitlist_position: number | null;
  notes:           string | null;
  session_label:   string;
  start_date:      string;
  end_date:        string;
  course_title:    string;
  course_code:     string;
}

export interface RegCustomerUpdate {
  name?:               string;
  phone?:              string;
  home_phone?:         string | null;
  email?:              string | null;
  mid?:                string | null;
  nickname?:           string | null;
  name_en?:            string | null;
  birth_date?:         string | null;
  nationality?:        string | null;
  blood_type?:         string | null;
  address?:            string | null;
  emergency_contact?:  string | null;
  emergency_phone?:    string | null;
  height?:             number | null;
  weight?:             number | null;
  shoe_size?:          number | null;
  vision_left?:        number | null;
  vision_right?:       number | null;
  payment_date?:       string | null;
  membership_expiry?:  string | null;
}

// ── 待處理清單 ───────────────────────────────────────────────
export interface TodoItem {
  id:               number;
  title:            string;
  note:             string | null;
  priority:         1 | 2 | 3;
  due_date:         string | null;
  ticket_id:        number | null;
  is_done:          number;
  done_at:          string | null;
  assignee_name:    string | null;
  created_by_name:  string | null;
  created_at:       string;
  updated_at:       string;
}

// ── RAG 知識庫 ────────────────────────────────────────────────
export interface KnowledgeChunk {
  id:            number;
  category:      'faq' | 'course' | 'policy' | 'general';
  title:         string;
  content:       string;
  is_active:     number;
  has_embedding: number;
  created_at:    string;
  updated_at:    string;
}

export interface RagSource {
  id:    number;
  title: string;
  score: number;
}
