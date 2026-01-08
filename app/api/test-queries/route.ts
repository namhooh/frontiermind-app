// app/api/test-queries/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { Pool } from 'pg';
import { testQueries } from '@/lib/testQueries';
import { requireAuth } from '@/lib/auth/helpers';

// Create PostgreSQL pool
const pool = new Pool({
  connectionString: process.env.SUPABASE_DB_URL,
});

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const queryId = searchParams.get('id');

  try {
    // Require authentication (staff can read)
    await requireAuth();

    if (!queryId) {
      // Return list of all queries without executing them
      return NextResponse.json({
        queries: testQueries.map(q => ({
          id: q.id,
          title: q.title,
          description: q.description
        }))
      });
    }

    const id = parseInt(queryId);
    const query = testQueries.find(q => q.id === id);

    if (!query) {
      return NextResponse.json(
        { error: 'Query not found' },
        { status: 404 }
      );
    }

    // Execute the SQL query
    const result = await pool.query(query.sql);

    return NextResponse.json({
      query: {
        id: query.id,
        title: query.title,
        description: query.description,
        sql: query.sql
      },
      data: result.rows,
      rowCount: result.rowCount
    });

  } catch (error) {
    // Handle authentication errors
    if (error instanceof Error &&
        (error.message === 'Unauthorized' ||
         error.message === 'Insufficient permissions' ||
         error.message === 'User role not found')) {
      return NextResponse.json(
        { error: error.message },
        { status: 401 }
      );
    }

    // Handle other errors
    console.error('Query execution error:', error);
    return NextResponse.json(
      {
        error: 'Failed to execute query',
        message: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    );
  }
}
