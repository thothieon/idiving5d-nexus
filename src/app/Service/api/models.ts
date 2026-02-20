export type TicketStatus = 'open' | 'pending' | 'closed';

export interface Dashboard {
  today_new: number;
  open_cnt: number;
  pending_cnt: number;
  overdue_60m: number;
}

export interface TicketListItem {
  ticket_id: number;
  status: TicketStatus;
  priority: string;
  subject: string | null;
  last_in_text: string | null;

  channel_type: string;
  updated_at: string;
  last_customer_message_at: string | null;

  customer_name: string | null;
  display_name: string | null;
  picture_url: string | null;
}

export interface TicketMessage {
  id: number;
  direction: 'in' | 'out';
  message_type: 'text' | 'image' | 'sticker' | string;

  text: string | null;

  content_url: string | null;
  content_path: string | null;

  sticker_id: string | null;
  sticker_url: string | null;

  created_at: string;

  sender_name: string | null;
  sender_picture_url: string | null;
}
