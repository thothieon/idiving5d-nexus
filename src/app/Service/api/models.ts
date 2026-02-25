// models.ts

// ── 舊有（保留相容）─────────────────────────────────────────
export type TicketStatus = 'open' | 'pending' | 'closed';

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
