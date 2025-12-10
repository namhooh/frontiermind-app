import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabaseClient";

export async function GET() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const hasKey = !!process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

  const { data, error } = await supabase
    .from("projects")
    .select("*")
    .limit(5);

  return NextResponse.json({
    supabaseUrl: url,
    hasPublishableKey: hasKey,
    rowCount: data?.length ?? 0,
    sample: data ?? [],
    error: error?.message ?? null,
  });
}
