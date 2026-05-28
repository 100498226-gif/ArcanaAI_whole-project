-- Arcana AI Chat Sessions and Feedback Schema
-- This stores all chat sessions, messages, and feedback for training improvements

-- Chat sessions table
CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL DEFAULT 'New Chat',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_compacted BOOLEAN NOT NULL DEFAULT FALSE,
  summary TEXT, -- Stores compacted summary when conversation is too long
  message_count INTEGER NOT NULL DEFAULT 0,
  total_tokens_estimate INTEGER NOT NULL DEFAULT 0
);

-- Messages table
CREATE TABLE IF NOT EXISTS public.chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  sources TEXT[], -- Array of source names (GitHub, Linear, etc.)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  token_estimate INTEGER NOT NULL DEFAULT 0
);

-- Feedback table for thumbs up/down
CREATE TABLE IF NOT EXISTS public.message_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
  session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
  rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
  correction TEXT, -- User-provided correction for negative feedback
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved BOOLEAN NOT NULL DEFAULT FALSE, -- Whether this feedback has been addressed in prompt
  UNIQUE(message_id) -- One feedback per message
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON public.chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON public.chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_session_id ON public.message_feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_feedback_unresolved ON public.message_feedback(resolved) WHERE resolved = FALSE;

-- Enable RLS (no auth required for this app, but good practice)
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_feedback ENABLE ROW LEVEL SECURITY;

-- Allow all operations (no auth in this app)
CREATE POLICY "Allow all on chat_sessions" ON public.chat_sessions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on chat_messages" ON public.chat_messages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on message_feedback" ON public.message_feedback FOR ALL USING (true) WITH CHECK (true);

-- Function to update session timestamp and message count
CREATE OR REPLACE FUNCTION update_session_on_message()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE public.chat_sessions
  SET 
    updated_at = NOW(),
    message_count = message_count + 1,
    total_tokens_estimate = total_tokens_estimate + NEW.token_estimate
  WHERE id = NEW.session_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update session when message is added
DROP TRIGGER IF EXISTS on_message_insert ON public.chat_messages;
CREATE TRIGGER on_message_insert
  AFTER INSERT ON public.chat_messages
  FOR EACH ROW
  EXECUTE FUNCTION update_session_on_message();
