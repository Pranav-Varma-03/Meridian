import { ChatWorkspace } from "@/components/chat-workspace";

export default function ConversationPage({ params }: { params: { conversationId: string } }) {
  return <ChatWorkspace conversationId={params.conversationId} />;
}
