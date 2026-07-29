import { DocumentLibrary } from "@/components/document-library";
import { getWorkspaceCapabilities } from "@/lib/server/capabilities";

export default async function DocumentsPage() {
  const { canReingest } = await getWorkspaceCapabilities();
  return <DocumentLibrary canReingest={canReingest} />;
}
