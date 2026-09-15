export type Product = {
  product_code: string;
  product_name: string;
  product_type: string;
  risk_level: string;
  expected_return: string;
  min_amount: string;
  term_days: number;
  fund_manager: string | null;
  fee_rate: string;
  status: string;
};

export type ProductFilters = {
  product_type?: string;
  risk_level?: string;
  min_amount?: string;
  min_expected_return?: string;
  max_term_days?: string;
};

export type ProductList = {
  products: Product[];
};
