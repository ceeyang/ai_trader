import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { DcaForm } from "../components/dca/DcaForm";
import { DcaResult } from "../components/dca/DcaResult";
import { Card, ErrorBanner, errorMessage } from "../components/ui";

export function DcaPage() {
  const calc = useMutation({ mutationFn: api.calculateDca });
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">定投计算</h1>
      <Card title="参数">
        <DcaForm onSubmit={(req) => calc.mutate(req)} loading={calc.isPending} />
      </Card>
      <ErrorBanner message={calc.isError ? errorMessage(calc.error) : null} />
      {calc.data && <DcaResult data={calc.data} />}
    </div>
  );
}
