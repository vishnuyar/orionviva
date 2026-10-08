"""Closed scenario premises, same-run starts and hypothetical summaries."""
from decimal import Decimal
from datetime import date
import calendar
import copy
import json
import re

from ..ledger.scenarios import ScenarioError, savings, loan_payoff, cash_flow, decimal, horizon, anchor
from .. import quantity
from .envelope import ToolResult, figure, bounded, refusal, HYPOTHETICAL, FINANCIAL
from .registry import _validate

SCENARIO_REQUESTS = {'scenario_annual_rate_required': {'loan_payoff_scenario': 'What nominal annual percentage rate should '
                                                           'this monthly scenario use? Resubmit the '
                                                           'whole scenario. Replace the bracketed '
                                                           'phrases, use the same three-letter currency '
                                                           'code throughout, separate each item with a '
                                                           'semicolon, use year-month-day dates, and '
                                                           'include each item once. Use “Simulate loan '
                                                           'payoff in [currency]: principal [currency] '
                                                           '[amount owed]; monthly payment [currency] '
                                                           '[payment]; nominal annual rate [percent]%; '
                                                           'horizon [months] months; first payment date '
                                                           '[date].” To start from a recorded liability '
                                                           'account, replace “principal [currency] '
                                                           '[amount owed]” with “starting account '
                                                           '[account name]”.',
                                   'savings_scenario': 'What nominal annual percentage rate should this '
                                                       'monthly scenario use? Resubmit the whole '
                                                       'scenario. Replace the bracketed phrases, use '
                                                       'the same three-letter currency code throughout, '
                                                       'separate each item with a semicolon, use '
                                                       'year-month-day dates, and include each item '
                                                       'once. Use “Simulate savings in [currency]: '
                                                       'initial amount [currency] [amount]; monthly '
                                                       'contribution [currency] [contribution]; nominal '
                                                       'annual rate [percent]%; horizon [months] '
                                                       'months; opening date [date].” To start from a '
                                                       'recorded account, replace “initial amount '
                                                       '[currency] [amount]” with “starting account '
                                                       '[account name]”.'},
 'scenario_calendar_range_unavailable': {'cash_flow_scenario': 'Please choose an opening or '
                                                               'first-payment date and a horizon that '
                                                               'fit within the supported calendar. '
                                                               'Resubmit the whole scenario. Replace '
                                                               'the bracketed phrases, use the same '
                                                               'three-letter currency code throughout, '
                                                               'separate each item with a semicolon, '
                                                               'use year-month-day dates, and include '
                                                               'each item once. Use “Simulate cash flow '
                                                               'in [currency]: initial amount '
                                                               '[currency] [cash]; monthly income '
                                                               '[currency] [incoming]; monthly outflow '
                                                               '[currency] [outgoing]; one-off outflow '
                                                               '[currency] [one-off amount]; one-off at '
                                                               'month [month]; horizon [months] months; '
                                                               'opening date [date].” To start from a '
                                                               'recorded account, replace “initial '
                                                               'amount [currency] [cash]” with '
                                                               '“starting account [account name]”.',
                                         'loan_payoff_scenario': 'Please choose an opening or '
                                                                 'first-payment date and a horizon that '
                                                                 'fit within the supported calendar. '
                                                                 'Resubmit the whole scenario. Replace '
                                                                 'the bracketed phrases, use the same '
                                                                 'three-letter currency code '
                                                                 'throughout, separate each item with a '
                                                                 'semicolon, use year-month-day dates, '
                                                                 'and include each item once. Use '
                                                                 '“Simulate loan payoff in [currency]: '
                                                                 'principal [currency] [amount owed]; '
                                                                 'monthly payment [currency] [payment]; '
                                                                 'nominal annual rate [percent]%; '
                                                                 'horizon [months] months; first '
                                                                 'payment date [date].” To start from a '
                                                                 'recorded liability account, replace '
                                                                 '“principal [currency] [amount owed]” '
                                                                 'with “starting account [account '
                                                                 'name]”.',
                                         'savings_scenario': 'Please choose an opening or first-payment '
                                                             'date and a horizon that fit within the '
                                                             'supported calendar. Resubmit the whole '
                                                             'scenario. Replace the bracketed phrases, '
                                                             'use the same three-letter currency code '
                                                             'throughout, separate each item with a '
                                                             'semicolon, use year-month-day dates, and '
                                                             'include each item once. Use “Simulate '
                                                             'savings in [currency]: initial amount '
                                                             '[currency] [amount]; monthly contribution '
                                                             '[currency] [contribution]; nominal annual '
                                                             'rate [percent]%; horizon [months] months; '
                                                             'opening date [date].” To start from a '
                                                             'recorded account, replace “initial amount '
                                                             '[currency] [amount]” with “starting '
                                                             'account [account name]”.'},
 'scenario_currency_required': {'cash_flow_scenario': 'Which currency should this scenario use? '
                                                      'Resubmit the whole scenario. Replace the '
                                                      'bracketed phrases, use the same three-letter '
                                                      'currency code throughout, separate each item '
                                                      'with a semicolon, use year-month-day dates, and '
                                                      'include each item once. Use “Simulate cash flow '
                                                      'in [currency]: initial amount [currency] [cash]; '
                                                      'monthly income [currency] [incoming]; monthly '
                                                      'outflow [currency] [outgoing]; one-off outflow '
                                                      '[currency] [one-off amount]; one-off at month '
                                                      '[month]; horizon [months] months; opening date '
                                                      '[date].” To start from a recorded account, '
                                                      'replace “initial amount [currency] [cash]” with '
                                                      '“starting account [account name]”.',
                                'loan_payoff_scenario': 'Which currency should this scenario use? '
                                                        'Resubmit the whole scenario. Replace the '
                                                        'bracketed phrases, use the same three-letter '
                                                        'currency code throughout, separate each item '
                                                        'with a semicolon, use year-month-day dates, '
                                                        'and include each item once. Use “Simulate loan '
                                                        'payoff in [currency]: principal [currency] '
                                                        '[amount owed]; monthly payment [currency] '
                                                        '[payment]; nominal annual rate [percent]%; '
                                                        'horizon [months] months; first payment date '
                                                        '[date].” To start from a recorded liability '
                                                        'account, replace “principal [currency] [amount '
                                                        'owed]” with “starting account [account name]”.',
                                'savings_scenario': 'Which currency should this scenario use? Resubmit '
                                                    'the whole scenario. Replace the bracketed phrases, '
                                                    'use the same three-letter currency code '
                                                    'throughout, separate each item with a semicolon, '
                                                    'use year-month-day dates, and include each item '
                                                    'once. Use “Simulate savings in [currency]: initial '
                                                    'amount [currency] [amount]; monthly contribution '
                                                    '[currency] [contribution]; nominal annual rate '
                                                    '[percent]%; horizon [months] months; opening date '
                                                    '[date].” To start from a recorded account, replace '
                                                    '“initial amount [currency] [amount]” with '
                                                    '“starting account [account name]”.'},
 'scenario_first_payment_date_required': {'loan_payoff_scenario': 'What is the first modeled payment '
                                                                  'date? Resubmit the whole scenario. '
                                                                  'Replace the bracketed phrases, use '
                                                                  'the same three-letter currency code '
                                                                  'throughout, separate each item with '
                                                                  'a semicolon, use year-month-day '
                                                                  'dates, and include each item once. '
                                                                  'Use “Simulate loan payoff in '
                                                                  '[currency]: principal [currency] '
                                                                  '[amount owed]; monthly payment '
                                                                  '[currency] [payment]; nominal annual '
                                                                  'rate [percent]%; horizon [months] '
                                                                  'months; first payment date [date].” '
                                                                  'To start from a recorded liability '
                                                                  'account, replace “principal '
                                                                  '[currency] [amount owed]” with '
                                                                  '“starting account [account name]”.'},
 'scenario_horizon_required': {'cash_flow_scenario': 'For how many months should this scenario run? '
                                                     'Resubmit the whole scenario. Replace the '
                                                     'bracketed phrases, use the same three-letter '
                                                     'currency code throughout, separate each item with '
                                                     'a semicolon, use year-month-day dates, and '
                                                     'include each item once. Use “Simulate cash flow '
                                                     'in [currency]: initial amount [currency] [cash]; '
                                                     'monthly income [currency] [incoming]; monthly '
                                                     'outflow [currency] [outgoing]; one-off outflow '
                                                     '[currency] [one-off amount]; one-off at month '
                                                     '[month]; horizon [months] months; opening date '
                                                     '[date].” To start from a recorded account, '
                                                     'replace “initial amount [currency] [cash]” with '
                                                     '“starting account [account name]”.',
                               'loan_payoff_scenario': 'For how many months should this scenario run? '
                                                       'Resubmit the whole scenario. Replace the '
                                                       'bracketed phrases, use the same three-letter '
                                                       'currency code throughout, separate each item '
                                                       'with a semicolon, use year-month-day dates, and '
                                                       'include each item once. Use “Simulate loan '
                                                       'payoff in [currency]: principal [currency] '
                                                       '[amount owed]; monthly payment [currency] '
                                                       '[payment]; nominal annual rate [percent]%; '
                                                       'horizon [months] months; first payment date '
                                                       '[date].” To start from a recorded liability '
                                                       'account, replace “principal [currency] [amount '
                                                       'owed]” with “starting account [account name]”.',
                               'savings_scenario': 'For how many months should this scenario run? '
                                                   'Resubmit the whole scenario. Replace the bracketed '
                                                   'phrases, use the same three-letter currency code '
                                                   'throughout, separate each item with a semicolon, '
                                                   'use year-month-day dates, and include each item '
                                                   'once. Use “Simulate savings in [currency]: initial '
                                                   'amount [currency] [amount]; monthly contribution '
                                                   '[currency] [contribution]; nominal annual rate '
                                                   '[percent]%; horizon [months] months; opening date '
                                                   '[date].” To start from a recorded account, replace '
                                                   '“initial amount [currency] [amount]” with “starting '
                                                   'account [account name]”.'},
 'scenario_monthly_contribution_required': {'savings_scenario': 'How much will you contribute each '
                                                                'month, and in which currency? Resubmit '
                                                                'the whole scenario. Replace the '
                                                                'bracketed phrases, use the same '
                                                                'three-letter currency code throughout, '
                                                                'separate each item with a semicolon, '
                                                                'use year-month-day dates, and include '
                                                                'each item once. Use “Simulate savings '
                                                                'in [currency]: initial amount '
                                                                '[currency] [amount]; monthly '
                                                                'contribution [currency] '
                                                                '[contribution]; nominal annual rate '
                                                                '[percent]%; horizon [months] months; '
                                                                'opening date [date].” To start from a '
                                                                'recorded account, replace “initial '
                                                                'amount [currency] [amount]” with '
                                                                '“starting account [account name]”.'},
 'scenario_monthly_income_required': {'cash_flow_scenario': 'How much incoming cash should each month '
                                                            'assume, and in which currency? Resubmit '
                                                            'the whole scenario. Replace the bracketed '
                                                            'phrases, use the same three-letter '
                                                            'currency code throughout, separate each '
                                                            'item with a semicolon, use year-month-day '
                                                            'dates, and include each item once. Use '
                                                            '“Simulate cash flow in [currency]: initial '
                                                            'amount [currency] [cash]; monthly income '
                                                            '[currency] [incoming]; monthly outflow '
                                                            '[currency] [outgoing]; one-off outflow '
                                                            '[currency] [one-off amount]; one-off at '
                                                            'month [month]; horizon [months] months; '
                                                            'opening date [date].” To start from a '
                                                            'recorded account, replace “initial amount '
                                                            '[currency] [cash]” with “starting account '
                                                            '[account name]”.'},
 'scenario_monthly_outflow_required': {'cash_flow_scenario': 'How much outgoing cash should each month '
                                                             'assume, and in which currency? Resubmit '
                                                             'the whole scenario. Replace the bracketed '
                                                             'phrases, use the same three-letter '
                                                             'currency code throughout, separate each '
                                                             'item with a semicolon, use year-month-day '
                                                             'dates, and include each item once. Use '
                                                             '“Simulate cash flow in [currency]: '
                                                             'initial amount [currency] [cash]; monthly '
                                                             'income [currency] [incoming]; monthly '
                                                             'outflow [currency] [outgoing]; one-off '
                                                             'outflow [currency] [one-off amount]; '
                                                             'one-off at month [month]; horizon '
                                                             '[months] months; opening date [date].” To '
                                                             'start from a recorded account, replace '
                                                             '“initial amount [currency] [cash]” with '
                                                             '“starting account [account name]”.'},
 'scenario_monthly_payment_required': {'loan_payoff_scenario': 'How much will you pay each month, and '
                                                               'in which currency? Resubmit the whole '
                                                               'scenario. Replace the bracketed '
                                                               'phrases, use the same three-letter '
                                                               'currency code throughout, separate each '
                                                               'item with a semicolon, use '
                                                               'year-month-day dates, and include each '
                                                               'item once. Use “Simulate loan payoff in '
                                                               '[currency]: principal [currency] '
                                                               '[amount owed]; monthly payment '
                                                               '[currency] [payment]; nominal annual '
                                                               'rate [percent]%; horizon [months] '
                                                               'months; first payment date [date].” To '
                                                               'start from a recorded liability '
                                                               'account, replace “principal [currency] '
                                                               '[amount owed]” with “starting account '
                                                               '[account name]”.'},
 'scenario_one_off_month_required': {'cash_flow_scenario': 'In which modeled month should the one-off '
                                                           'outgoing amount occur? Resubmit the whole '
                                                           'scenario. Replace the bracketed phrases, '
                                                           'use the same three-letter currency code '
                                                           'throughout, separate each item with a '
                                                           'semicolon, use year-month-day dates, and '
                                                           'include each item once. Use “Simulate cash '
                                                           'flow in [currency]: initial amount '
                                                           '[currency] [cash]; monthly income '
                                                           '[currency] [incoming]; monthly outflow '
                                                           '[currency] [outgoing]; one-off outflow '
                                                           '[currency] [one-off amount]; one-off at '
                                                           'month [month]; horizon [months] months; '
                                                           'opening date [date].” To start from a '
                                                           'recorded account, replace “initial amount '
                                                           '[currency] [cash]” with “starting account '
                                                           '[account name]”.'},
 'scenario_one_off_outflow_required': {'cash_flow_scenario': 'What one-off outgoing amount should this '
                                                             'cash scenario assume, and in which '
                                                             'currency? State zero if there is none. '
                                                             'Resubmit the whole scenario. Replace the '
                                                             'bracketed phrases, use the same '
                                                             'three-letter currency code throughout, '
                                                             'separate each item with a semicolon, use '
                                                             'year-month-day dates, and include each '
                                                             'item once. Use “Simulate cash flow in '
                                                             '[currency]: initial amount [currency] '
                                                             '[cash]; monthly income [currency] '
                                                             '[incoming]; monthly outflow [currency] '
                                                             '[outgoing]; one-off outflow [currency] '
                                                             '[one-off amount]; one-off at month '
                                                             '[month]; horizon [months] months; opening '
                                                             'date [date].” To start from a recorded '
                                                             'account, replace “initial amount '
                                                             '[currency] [cash]” with “starting account '
                                                             '[account name]”.'},
 'scenario_opening_date_required': {'cash_flow_scenario': 'What opening date should this scenario use? '
                                                          'Resubmit the whole scenario. Replace the '
                                                          'bracketed phrases, use the same three-letter '
                                                          'currency code throughout, separate each item '
                                                          'with a semicolon, use year-month-day dates, '
                                                          'and include each item once. Use “Simulate '
                                                          'cash flow in [currency]: initial amount '
                                                          '[currency] [cash]; monthly income [currency] '
                                                          '[incoming]; monthly outflow [currency] '
                                                          '[outgoing]; one-off outflow [currency] '
                                                          '[one-off amount]; one-off at month [month]; '
                                                          'horizon [months] months; opening date '
                                                          '[date].” To start from a recorded account, '
                                                          'replace “initial amount [currency] [cash]” '
                                                          'with “starting account [account name]”.',
                                    'savings_scenario': 'What opening date should this scenario use? '
                                                        'Resubmit the whole scenario. Replace the '
                                                        'bracketed phrases, use the same three-letter '
                                                        'currency code throughout, separate each item '
                                                        'with a semicolon, use year-month-day dates, '
                                                        'and include each item once. Use “Simulate '
                                                        'savings in [currency]: initial amount '
                                                        '[currency] [amount]; monthly contribution '
                                                        '[currency] [contribution]; nominal annual rate '
                                                        '[percent]%; horizon [months] months; opening '
                                                        'date [date].” To start from a recorded '
                                                        'account, replace “initial amount [currency] '
                                                        '[amount]” with “starting account [account '
                                                        'name]”.'},
 'scenario_non_amortizing_payment': {'cash_flow_scenario': 'The stated monthly payment does not exceed '
                                                           'the initial modeled monthly interest. '
                                                           'Provide a larger payment. Resubmit the '
                                                           'whole scenario. Replace the bracketed '
                                                           'phrases, use the same three-letter currency '
                                                           'code throughout, separate each item with a '
                                                           'semicolon, use year-month-day dates, and '
                                                           'include each item once. Use “Simulate cash '
                                                           'flow in [currency]: initial amount '
                                                           '[currency] [cash]; monthly income '
                                                           '[currency] [incoming]; monthly outflow '
                                                           '[currency] [outgoing]; one-off outflow '
                                                           '[currency] [one-off amount]; one-off at '
                                                           'month [month]; horizon [months] months; '
                                                           'opening date [date].” To start from a '
                                                           'recorded account, replace “initial amount '
                                                           '[currency] [cash]” with “starting account '
                                                           '[account name]”.',
                                     'loan_payoff_scenario': 'The stated monthly payment does not '
                                                             'exceed the initial modeled monthly '
                                                             'interest. Provide a larger payment. '
                                                             'Resubmit the whole scenario. Replace the '
                                                             'bracketed phrases, use the same '
                                                             'three-letter currency code throughout, '
                                                             'separate each item with a semicolon, use '
                                                             'year-month-day dates, and include each '
                                                             'item once. Use “Simulate loan payoff in '
                                                             '[currency]: principal [currency] [amount '
                                                             'owed]; monthly payment [currency] '
                                                             '[payment]; nominal annual rate '
                                                             '[percent]%; horizon [months] months; '
                                                             'first payment date [date].” To start from '
                                                             'a recorded liability account, replace '
                                                             '“principal [currency] [amount owed]” with '
                                                             '“starting account [account name]”.',
                                     'savings_scenario': 'The stated monthly payment does not exceed '
                                                         'the initial modeled monthly interest. Provide '
                                                         'a larger payment. Resubmit the whole '
                                                         'scenario. Replace the bracketed phrases, use '
                                                         'the same three-letter currency code '
                                                         'throughout, separate each item with a '
                                                         'semicolon, use year-month-day dates, and '
                                                         'include each item once. Use “Simulate savings '
                                                         'in [currency]: initial amount [currency] '
                                                         '[amount]; monthly contribution [currency] '
                                                         '[contribution]; nominal annual rate '
                                                         '[percent]%; horizon [months] months; opening '
                                                         'date [date].” To start from a recorded '
                                                         'account, replace “initial amount [currency] '
                                                         '[amount]” with “starting account [account '
                                                         'name]”.'},
 'scenario_payment_rounds_to_zero': {'cash_flow_scenario': 'The stated payment rounds to zero under '
                                                           'this calculator’s cent convention. Provide '
                                                           'a payment that remains positive after '
                                                           'rounding. Resubmit the whole scenario. '
                                                           'Replace the bracketed phrases, use the same '
                                                           'three-letter currency code throughout, '
                                                           'separate each item with a semicolon, use '
                                                           'year-month-day dates, and include each item '
                                                           'once. Use “Simulate cash flow in '
                                                           '[currency]: initial amount [currency] '
                                                           '[cash]; monthly income [currency] '
                                                           '[incoming]; monthly outflow [currency] '
                                                           '[outgoing]; one-off outflow [currency] '
                                                           '[one-off amount]; one-off at month [month]; '
                                                           'horizon [months] months; opening date '
                                                           '[date].” To start from a recorded account, '
                                                           'replace “initial amount [currency] [cash]” '
                                                           'with “starting account [account name]”.',
                                     'loan_payoff_scenario': 'The stated payment rounds to zero under '
                                                             'this calculator’s cent convention. '
                                                             'Provide a payment that remains positive '
                                                             'after rounding. Resubmit the whole '
                                                             'scenario. Replace the bracketed phrases, '
                                                             'use the same three-letter currency code '
                                                             'throughout, separate each item with a '
                                                             'semicolon, use year-month-day dates, and '
                                                             'include each item once. Use “Simulate '
                                                             'loan payoff in [currency]: principal '
                                                             '[currency] [amount owed]; monthly payment '
                                                             '[currency] [payment]; nominal annual rate '
                                                             '[percent]%; horizon [months] months; '
                                                             'first payment date [date].” To start from '
                                                             'a recorded liability account, replace '
                                                             '“principal [currency] [amount owed]” with '
                                                             '“starting account [account name]”.',
                                     'savings_scenario': 'The stated payment rounds to zero under this '
                                                         'calculator’s cent convention. Provide a '
                                                         'payment that remains positive after rounding. '
                                                         'Resubmit the whole scenario. Replace the '
                                                         'bracketed phrases, use the same three-letter '
                                                         'currency code throughout, separate each item '
                                                         'with a semicolon, use year-month-day dates, '
                                                         'and include each item once. Use “Simulate '
                                                         'savings in [currency]: initial amount '
                                                         '[currency] [amount]; monthly contribution '
                                                         '[currency] [contribution]; nominal annual '
                                                         'rate [percent]%; horizon [months] months; '
                                                         'opening date [date].” To start from a '
                                                         'recorded account, replace “initial amount '
                                                         '[currency] [amount]” with “starting account '
                                                         '[account name]”.'},
 'scenario_premise_source_mismatch': {'cash_flow_scenario': 'Please restate the scenario assumptions '
                                                            'with each value beside its meaning and '
                                                            'currency or unit. Resubmit the whole '
                                                            'scenario. Replace the bracketed phrases, '
                                                            'use the same three-letter currency code '
                                                            'throughout, separate each item with a '
                                                            'semicolon, use year-month-day dates, and '
                                                            'include each item once. Use “Simulate cash '
                                                            'flow in [currency]: initial amount '
                                                            '[currency] [cash]; monthly income '
                                                            '[currency] [incoming]; monthly outflow '
                                                            '[currency] [outgoing]; one-off outflow '
                                                            '[currency] [one-off amount]; one-off at '
                                                            'month [month]; horizon [months] months; '
                                                            'opening date [date].” To start from a '
                                                            'recorded account, replace “initial amount '
                                                            '[currency] [cash]” with “starting account '
                                                            '[account name]”.',
                                      'loan_payoff_scenario': 'Please restate the scenario assumptions '
                                                              'with each value beside its meaning and '
                                                              'currency or unit. Resubmit the whole '
                                                              'scenario. Replace the bracketed phrases, '
                                                              'use the same three-letter currency code '
                                                              'throughout, separate each item with a '
                                                              'semicolon, use year-month-day dates, and '
                                                              'include each item once. Use “Simulate '
                                                              'loan payoff in [currency]: principal '
                                                              '[currency] [amount owed]; monthly '
                                                              'payment [currency] [payment]; nominal '
                                                              'annual rate [percent]%; horizon [months] '
                                                              'months; first payment date [date].” To '
                                                              'start from a recorded liability account, '
                                                              'replace “principal [currency] [amount '
                                                              'owed]” with “starting account [account '
                                                              'name]”.',
                                      'savings_scenario': 'Please restate the scenario assumptions with '
                                                          'each value beside its meaning and currency '
                                                          'or unit. Resubmit the whole scenario. '
                                                          'Replace the bracketed phrases, use the same '
                                                          'three-letter currency code throughout, '
                                                          'separate each item with a semicolon, use '
                                                          'year-month-day dates, and include each item '
                                                          'once. Use “Simulate savings in [currency]: '
                                                          'initial amount [currency] [amount]; monthly '
                                                          'contribution [currency] [contribution]; '
                                                          'nominal annual rate [percent]%; horizon '
                                                          '[months] months; opening date [date].” To '
                                                          'start from a recorded account, replace '
                                                          '“initial amount [currency] [amount]” with '
                                                          '“starting account [account name]”.'},
 'scenario_principal_required': {'loan_payoff_scenario': 'What starting amount owed should this loan '
                                                         'scenario use, or which recorded liability '
                                                         'account should supply it? Resubmit the whole '
                                                         'scenario. Replace the bracketed phrases, use '
                                                         'the same three-letter currency code '
                                                         'throughout, separate each item with a '
                                                         'semicolon, use year-month-day dates, and '
                                                         'include each item once. Use “Simulate loan '
                                                         'payoff in [currency]: principal [currency] '
                                                         '[amount owed]; monthly payment [currency] '
                                                         '[payment]; nominal annual rate [percent]%; '
                                                         'horizon [months] months; first payment date '
                                                         '[date].” To start from a recorded liability '
                                                         'account, replace “principal [currency] '
                                                         '[amount owed]” with “starting account '
                                                         '[account name]”.'},
 'scenario_rate_basis_unavailable': {'loan_payoff_scenario': 'What nominal annual percentage rate '
                                                             'should this monthly scenario use? '
                                                             'Resubmit the whole scenario. Replace the '
                                                             'bracketed phrases, use the same '
                                                             'three-letter currency code throughout, '
                                                             'separate each item with a semicolon, use '
                                                             'year-month-day dates, and include each '
                                                             'item once. Use “Simulate loan payoff in '
                                                             '[currency]: principal [currency] [amount '
                                                             'owed]; monthly payment [currency] '
                                                             '[payment]; nominal annual rate '
                                                             '[percent]%; horizon [months] months; '
                                                             'first payment date [date].” To start from '
                                                             'a recorded liability account, replace '
                                                             '“principal [currency] [amount owed]” with '
                                                             '“starting account [account name]”.',
                                     'savings_scenario': 'What nominal annual percentage rate should '
                                                         'this monthly scenario use? Resubmit the whole '
                                                         'scenario. Replace the bracketed phrases, use '
                                                         'the same three-letter currency code '
                                                         'throughout, separate each item with a '
                                                         'semicolon, use year-month-day dates, and '
                                                         'include each item once. Use “Simulate savings '
                                                         'in [currency]: initial amount [currency] '
                                                         '[amount]; monthly contribution [currency] '
                                                         '[contribution]; nominal annual rate '
                                                         '[percent]%; horizon [months] months; opening '
                                                         'date [date].” To start from a recorded '
                                                         'account, replace “initial amount [currency] '
                                                         '[amount]” with “starting account [account '
                                                         'name]”.'},
 'scenario_source_context_unavailable': {'cash_flow_scenario': 'Please state one current set of '
                                                               'assumptions, naming each amount, rate '
                                                               'and date once. Resubmit the whole '
                                                               'scenario. Replace the bracketed '
                                                               'phrases, use the same three-letter '
                                                               'currency code throughout, separate each '
                                                               'item with a semicolon, use '
                                                               'year-month-day dates, and include each '
                                                               'item once. Use “Simulate cash flow in '
                                                               '[currency]: initial amount [currency] '
                                                               '[cash]; monthly income [currency] '
                                                               '[incoming]; monthly outflow [currency] '
                                                               '[outgoing]; one-off outflow [currency] '
                                                               '[one-off amount]; one-off at month '
                                                               '[month]; horizon [months] months; '
                                                               'opening date [date].” To start from a '
                                                               'recorded account, replace “initial '
                                                               'amount [currency] [cash]” with '
                                                               '“starting account [account name]”.',
                                         'loan_payoff_scenario': 'Please state one current set of '
                                                                 'assumptions, naming each amount, rate '
                                                                 'and date once. Resubmit the whole '
                                                                 'scenario. Replace the bracketed '
                                                                 'phrases, use the same three-letter '
                                                                 'currency code throughout, separate '
                                                                 'each item with a semicolon, use '
                                                                 'year-month-day dates, and include '
                                                                 'each item once. Use “Simulate loan '
                                                                 'payoff in [currency]: principal '
                                                                 '[currency] [amount owed]; monthly '
                                                                 'payment [currency] [payment]; nominal '
                                                                 'annual rate [percent]%; horizon '
                                                                 '[months] months; first payment date '
                                                                 '[date].” To start from a recorded '
                                                                 'liability account, replace “principal '
                                                                 '[currency] [amount owed]” with '
                                                                 '“starting account [account name]”.',
                                         'savings_scenario': 'Please state one current set of '
                                                             'assumptions, naming each amount, rate and '
                                                             'date once. Resubmit the whole scenario. '
                                                             'Replace the bracketed phrases, use the '
                                                             'same three-letter currency code '
                                                             'throughout, separate each item with a '
                                                             'semicolon, use year-month-day dates, and '
                                                             'include each item once. Use “Simulate '
                                                             'savings in [currency]: initial amount '
                                                             '[currency] [amount]; monthly contribution '
                                                             '[currency] [contribution]; nominal annual '
                                                             'rate [percent]%; horizon [months] months; '
                                                             'opening date [date].” To start from a '
                                                             'recorded account, replace “initial amount '
                                                             '[currency] [amount]” with “starting '
                                                             'account [account name]”.'},
 'scenario_starting_account_ambiguous': {'cash_flow_scenario': 'Which recorded account should supply '
                                                               'the scenario opening value? Resubmit '
                                                               'the whole scenario. Replace the '
                                                               'bracketed phrases, use the same '
                                                               'three-letter currency code throughout, '
                                                               'separate each item with a semicolon, '
                                                               'use year-month-day dates, and include '
                                                               'each item once. Use “Simulate cash flow '
                                                               'in [currency]: initial amount '
                                                               '[currency] [cash]; monthly income '
                                                               '[currency] [incoming]; monthly outflow '
                                                               '[currency] [outgoing]; one-off outflow '
                                                               '[currency] [one-off amount]; one-off at '
                                                               'month [month]; horizon [months] months; '
                                                               'opening date [date].” To start from a '
                                                               'recorded account, replace “initial '
                                                               'amount [currency] [cash]” with '
                                                               '“starting account [account name]”.',
                                         'loan_payoff_scenario': 'Which recorded account should supply '
                                                                 'the scenario opening value? Resubmit '
                                                                 'the whole scenario. Replace the '
                                                                 'bracketed phrases, use the same '
                                                                 'three-letter currency code '
                                                                 'throughout, separate each item with a '
                                                                 'semicolon, use year-month-day dates, '
                                                                 'and include each item once. Use '
                                                                 '“Simulate loan payoff in [currency]: '
                                                                 'principal [currency] [amount owed]; '
                                                                 'monthly payment [currency] [payment]; '
                                                                 'nominal annual rate [percent]%; '
                                                                 'horizon [months] months; first '
                                                                 'payment date [date].” To start from a '
                                                                 'recorded liability account, replace '
                                                                 '“principal [currency] [amount owed]” '
                                                                 'with “starting account [account '
                                                                 'name]”.',
                                         'savings_scenario': 'Which recorded account should supply the '
                                                             'scenario opening value? Resubmit the '
                                                             'whole scenario. Replace the bracketed '
                                                             'phrases, use the same three-letter '
                                                             'currency code throughout, separate each '
                                                             'item with a semicolon, use year-month-day '
                                                             'dates, and include each item once. Use '
                                                             '“Simulate savings in [currency]: initial '
                                                             'amount [currency] [amount]; monthly '
                                                             'contribution [currency] [contribution]; '
                                                             'nominal annual rate [percent]%; horizon '
                                                             '[months] months; opening date [date].” To '
                                                             'start from a recorded account, replace '
                                                             '“initial amount [currency] [amount]” with '
                                                             '“starting account [account name]”.'},
 'scenario_starting_amount_required': {'cash_flow_scenario': 'What opening amount should this scenario '
                                                             'use, or which recorded account should '
                                                             'supply it? Resubmit the whole scenario. '
                                                             'Replace the bracketed phrases, use the '
                                                             'same three-letter currency code '
                                                             'throughout, separate each item with a '
                                                             'semicolon, use year-month-day dates, and '
                                                             'include each item once. Use “Simulate '
                                                             'cash flow in [currency]: initial amount '
                                                             '[currency] [cash]; monthly income '
                                                             '[currency] [incoming]; monthly outflow '
                                                             '[currency] [outgoing]; one-off outflow '
                                                             '[currency] [one-off amount]; one-off at '
                                                             'month [month]; horizon [months] months; '
                                                             'opening date [date].” To start from a '
                                                             'recorded account, replace “initial amount '
                                                             '[currency] [cash]” with “starting account '
                                                             '[account name]”.',
                                       'savings_scenario': 'What opening amount should this scenario '
                                                           'use, or which recorded account should '
                                                           'supply it? Resubmit the whole scenario. '
                                                           'Replace the bracketed phrases, use the same '
                                                           'three-letter currency code throughout, '
                                                           'separate each item with a semicolon, use '
                                                           'year-month-day dates, and include each item '
                                                           'once. Use “Simulate savings in [currency]: '
                                                           'initial amount [currency] [amount]; monthly '
                                                           'contribution [currency] [contribution]; '
                                                           'nominal annual rate [percent]%; horizon '
                                                           '[months] months; opening date [date].” To '
                                                           'start from a recorded account, replace '
                                                           '“initial amount [currency] [amount]” with '
                                                           '“starting account [account name]”.'},
 'scenario_starting_basis_ambiguous': {'cash_flow_scenario': 'Should the scenario use your stated '
                                                             'opening amount or one recorded account? '
                                                             'Choose one. Resubmit the whole scenario. '
                                                             'Replace the bracketed phrases, use the '
                                                             'same three-letter currency code '
                                                             'throughout, separate each item with a '
                                                             'semicolon, use year-month-day dates, and '
                                                             'include each item once. Use “Simulate '
                                                             'cash flow in [currency]: initial amount '
                                                             '[currency] [cash]; monthly income '
                                                             '[currency] [incoming]; monthly outflow '
                                                             '[currency] [outgoing]; one-off outflow '
                                                             '[currency] [one-off amount]; one-off at '
                                                             'month [month]; horizon [months] months; '
                                                             'opening date [date].” To start from a '
                                                             'recorded account, replace “initial amount '
                                                             '[currency] [cash]” with “starting account '
                                                             '[account name]”.',
                                       'loan_payoff_scenario': 'Should the scenario use your stated '
                                                               'opening amount or one recorded account? '
                                                               'Choose one. Resubmit the whole '
                                                               'scenario. Replace the bracketed '
                                                               'phrases, use the same three-letter '
                                                               'currency code throughout, separate each '
                                                               'item with a semicolon, use '
                                                               'year-month-day dates, and include each '
                                                               'item once. Use “Simulate loan payoff in '
                                                               '[currency]: principal [currency] '
                                                               '[amount owed]; monthly payment '
                                                               '[currency] [payment]; nominal annual '
                                                               'rate [percent]%; horizon [months] '
                                                               'months; first payment date [date].” To '
                                                               'start from a recorded liability '
                                                               'account, replace “principal [currency] '
                                                               '[amount owed]” with “starting account '
                                                               '[account name]”.',
                                       'savings_scenario': 'Should the scenario use your stated opening '
                                                           'amount or one recorded account? Choose one. '
                                                           'Resubmit the whole scenario. Replace the '
                                                           'bracketed phrases, use the same '
                                                           'three-letter currency code throughout, '
                                                           'separate each item with a semicolon, use '
                                                           'year-month-day dates, and include each item '
                                                           'once. Use “Simulate savings in [currency]: '
                                                           'initial amount [currency] [amount]; monthly '
                                                           'contribution [currency] [contribution]; '
                                                           'nominal annual rate [percent]%; horizon '
                                                           '[months] months; opening date [date].” To '
                                                           'start from a recorded account, replace '
                                                           '“initial amount [currency] [amount]” with '
                                                           '“starting account [account name]”.'}}

for _tag in ('scenario_payment_rounds_to_zero','scenario_non_amortizing_payment'):
    SCENARIO_REQUESTS[_tag] = {'loan_payoff_scenario':SCENARIO_REQUESTS[_tag]['loan_payoff_scenario']}

FAMILIES = ('savings_scenario','loan_payoff_scenario','cash_flow_scenario')
HEADERS = dict(zip(FAMILIES,('Simulate savings','Simulate loan payoff','Simulate cash flow')))
MONEY_ROLES = {'initial_amount':'initial amount','initial_cash':'initial amount','principal':'principal',
               'monthly_contribution':'monthly contribution','monthly_payment':'monthly payment',
               'monthly_income':'monthly income','monthly_outflow':'monthly outflow','one_off_outflow':'one-off outflow'}
INPUTS = {
    'savings_scenario':('initial_amount','monthly_contribution','nominal_annual_rate_percent','months','start_date','currency'),
    'loan_payoff_scenario':('principal','monthly_payment','nominal_annual_rate_percent','months','start_date','currency'),
    'cash_flow_scenario':('initial_cash','monthly_income','monthly_outflow','one_off_outflow','one_off_month','months','start_date','currency'),
}
MISSING_TAGS = {'initial_amount':'scenario_starting_amount_required','initial_cash':'scenario_starting_amount_required',
 'principal':'scenario_principal_required','monthly_contribution':'scenario_monthly_contribution_required',
 'monthly_payment':'scenario_monthly_payment_required','monthly_income':'scenario_monthly_income_required',
 'monthly_outflow':'scenario_monthly_outflow_required','one_off_outflow':'scenario_one_off_outflow_required',
 'one_off_month':'scenario_one_off_month_required','nominal_annual_rate_percent':'scenario_annual_rate_required',
 'months':'scenario_horizon_required','currency':'scenario_currency_required'}
_NUM = r'[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,6})?'
_SYMBOLS = {'USD':'$','EUR':'€','GBP':'£','JPY':'¥'}
_STRING = {'type':'string','minLength':1}
PROOF = {'type':'object','additionalProperties':False,'properties':{
    'source':{'type':'string','enum':['question']},'quote':_STRING,
    'derivation':{'type':'string','enum':['decimal_numeric','verbatim','catalog_selection','calendar_month_start','calendar_month_end']}},
    'required':['source','quote','derivation']}
PARAMETER_PROPERTIES = {key:_STRING for key in {*MONEY_ROLES,'nominal_annual_rate_percent','months','one_off_month','start_date','currency','account_phrase'}}
SCENARIO_PARAMS = {'type':'object','additionalProperties':False,'properties':{
    'view':{'type':'string','enum':list(FAMILIES)},
    'parameters':{'type':'object','additionalProperties':False,'properties':PARAMETER_PROPERTIES},
    'parameter_sources':{'type':'object','additionalProperties':False,'properties':{key:PROOF for key in PARAMETER_PROPERTIES}},
    'starting_figure':{'oneOf':[_STRING,{'type':'object','additionalProperties':False,'properties':{'ref':{'type':'object','additionalProperties':False,'properties':{'node':_STRING,'value':{'type':'string','enum':['unique_figure_id']}},'required':['node','value']}},'required':['ref']}]}},'required':['view','parameters','parameter_sources']}


def scenario_request(tag, family):
    if tag == 'scenario_payload_limit' and family in FAMILIES:
        guidance = SCENARIO_REQUESTS['scenario_premise_source_mismatch'][family].partition('Resubmit the whole scenario.')[2]
        return ('This scenario and its recorded source details are too large for one answer. '
                'A stated opening amount can be used instead of a recorded account. '
                'Resubmit the whole scenario.' + guidance)
    return SCENARIO_REQUESTS.get(tag,{}).get(family,'')


def _fail(tag='scenario_premise_source_mismatch'):
    raise ScenarioError(tag)


def validate_premises(family, parameters, proofs, question):
    """Validate an explicit current-question source scope after family selection."""
    if family not in FAMILIES or not isinstance(parameters,dict) or not isinstance(proofs,dict):
        _fail()
    if set(parameters)-set(INPUTS[family])-{'account_phrase'}:
        _fail()
    if not isinstance(question,str):
        _fail('scenario_source_context_unavailable')
    held = question.strip()
    if held.endswith('.'):
        held = held[:-1]
    match = re.fullmatch(re.escape(HEADERS[family])+r'\s+in\s+([A-Z]{3}):\s*(.+)',held,re.IGNORECASE|re.ASCII)
    if not match or match.group(1) != match.group(1).upper():
        _fail('scenario_source_context_unavailable')
    currency, body = match.groups()
    clauses = [part.strip() for part in body.split(';')]
    parsed = {}
    date_role = 'first payment date' if family=='loan_payoff_scenario' else 'opening date'
    start_name = INPUTS[family][0]
    for clause in clauses:
        found = None
        for name in INPUTS[family]:
            if name in MONEY_ROLES:
                unit = '(?:'+re.escape(currency)+('|'+re.escape(_SYMBOLS[currency]) if currency in _SYMBOLS else '')+')'
                form = re.fullmatch(re.escape(MONEY_ROLES[name])+r'\s+(?:'+unit+r'\s*('+_NUM+r')|('+_NUM+r')\s*'+unit+r')',clause,re.IGNORECASE|re.ASCII)
                if form:
                    found = name, next(value for value in form.groups() if value is not None), 'decimal_numeric'
            elif name == 'nominal_annual_rate_percent':
                form = re.fullmatch(r'nominal annual rate\s+('+_NUM+r')\s*(?:%|percent)',clause,re.IGNORECASE|re.ASCII)
                if form: found = name,form.group(1),'decimal_numeric'
            elif name in {'months','one_off_month'}:
                form = re.fullmatch(r'horizon\s+([0-9]+)\s+months?' if name=='months' else r'one-off at month\s+([0-9]+)',clause,re.IGNORECASE|re.ASCII)
                if form: found = name,form.group(1),'decimal_numeric'
            elif name == 'start_date':
                form = re.fullmatch(re.escape(date_role)+r'\s+([0-9]{4}-[0-9]{2}-[0-9]{2})',clause,re.IGNORECASE|re.ASCII)
                if form: found = name,anchor(form.group(1)).isoformat(),'verbatim'
                else:
                    edge = re.fullmatch(re.escape(date_role)+r'\s+at\s+(start|end)\s+of\s+([A-Za-z]+)\s+([0-9]{4})',clause,re.IGNORECASE|re.ASCII)
                    if edge:
                        months = {month.lower():i for i,month in enumerate(calendar.month_name) if month}
                        month = months.get(edge.group(2).lower())
                        year = int(edge.group(3))
                        if not month or not 1<=year<=9999: _fail()
                        end = edge.group(1).lower()=='end'
                        found = name,date(year,month,calendar.monthrange(year,month)[1] if end else 1).isoformat(),'calendar_month_end' if end else 'calendar_month_start'
        account = re.fullmatch(r'starting account\s+([^;:"()]+)',clause,re.IGNORECASE)
        if account: found = 'account_phrase',account.group(1).strip(),'catalog_selection'
        if found is None:
            if re.fullmatch(r'(?:nominal annual rate|annual rate|monthly rate|APY|APR)\s+.+',clause,re.IGNORECASE):
                _fail('scenario_rate_basis_unavailable')
            _fail('scenario_source_context_unavailable')
        name, raw, derivation = found
        if name in parsed: _fail('scenario_source_context_unavailable')
        parsed[name] = (raw,clause,derivation)
    parsed['currency'] = (currency,currency,'verbatim')
    if start_name in parsed and 'account_phrase' in parsed:
        _fail('scenario_starting_basis_ambiguous')
    required = set(INPUTS[family]) - ({start_name} if 'account_phrase' in parsed else set())
    for name in INPUTS[family]:
        if name in required and name not in parsed:
            _fail(('scenario_first_payment_date_required' if family=='loan_payoff_scenario' else 'scenario_opening_date_required') if name=='start_date' else MISSING_TAGS[name])
    if set(parameters) != set(parsed) or set(proofs) != set(parameters):
        _fail()
    for name, (raw,clause,derivation) in parsed.items():
        proof = proofs.get(name)
        if not isinstance(proof,dict) or set(proof)!={'source','quote','derivation'} or proof['source']!='question' or proof['derivation']!=derivation:
            _fail()
        if name=='account_phrase':
            if proof['quote'] != raw or not parameters[name]: _fail()
        elif proof['quote'] != clause or parameters[name] != raw.replace(',',''):
            _fail()
        if name in MONEY_ROLES or name=='nominal_annual_rate_percent':
            value = decimal(raw.replace(',',''))
            if name=='nominal_annual_rate_percent' and value>100: _fail()
        if name in {'months','one_off_month'}:
            horizon(raw)
    if 'one_off_month' in parameters and int(parameters['one_off_month'])>int(parameters['months']): _fail()
    return {'current_question_only':True,'hypothetical_grades_empty':True,'parameter_role_binding':True,
            'whole_positive_current_question':True,'unique_complete_role_clauses':True,'forbid_prior_assistant_scalars':True,
            'currency_header':currency,'declared_start_date':parameters['start_date'],'declared_months':parameters['months'],
            'exact_proofs':copy.deepcopy(proofs),'exact_parameters':copy.deepcopy(parameters),
            **({'starting_account_clause':parsed['account_phrase'][1]} if 'account_phrase' in parsed else {})}


def simulate_scenario(args, figures, question='', *, account_resolver=None):
    tool = 'simulate_scenario'
    if not isinstance(args,dict) or _validate(SCENARIO_PARAMS,args):
        if isinstance(args,dict) and args.get('view') in FAMILIES:
            tag='scenario_premise_source_mismatch'
            return refusal(tool,tag,scenario_request(tag,args['view']))
        return refusal(tool,'invalid_arguments','Select one closed scenario and its typed premises.')
    family = args['view']
    if 'starting_figure' in args and (not isinstance(args['starting_figure'],str) or not args['starting_figure'].strip()):
        return refusal(tool,'invalid_arguments','A starting measurement must resolve to a same-run figure.')
    parameters = args['parameters']
    try:
        receipt = validate_premises(family,parameters,args['parameter_sources'],question)
        money = copy.deepcopy(parameters)
        start_name = INPUTS[family][0]
        sources = []
        observed = None
        if 'account_phrase' in parameters:
            quote = args['parameter_sources']['account_phrase']['quote']
            candidates = account_resolver(quote) if callable(account_resolver) else []
            if len(candidates) != 1 or candidates[0]['id'] != parameters['account_phrase']:
                _fail()
            fid = args.get('starting_figure')
            observed = figures.get(fid) if isinstance(figures,dict) else None
            expected_quantity = quantity.OWED if family=='loan_payoff_scenario' else quantity.BALANCE
            expected_view = 'recorded_owed' if family=='loan_payoff_scenario' else 'recorded_cash'
            if (not isinstance(observed,dict) or observed.get('id')!=fid or observed.get('kind')!=FINANCIAL
                    or observed.get('measurement_view')!=expected_view
                    or observed.get('quantity')!=expected_quantity or observed.get('currency')!=parameters['currency']
                    or not observed.get('dated') or not observed.get('record_ids')
                    or observed.get('boundary',{}).get('selected') != [{'kind':'account','value':parameters['account_phrase']}]
                    or observed.get('boundary',{}).get('cut') != [{'kind':'account','value':parameters['account_phrase']}]):
                _fail()
            anchor(observed['dated'])
            money[start_name] = observed['value']
            decimal(money[start_name])
            sources = list(observed['record_ids'])
            receipt['observed_start'] = copy.deepcopy(observed)
        elif 'starting_figure' in args:
            _fail('scenario_starting_basis_ambiguous')
        if family=='savings_scenario':
            result = savings(*(money[key] for key in INPUTS[family] if key!='currency'))
        elif family=='loan_payoff_scenario':
            result = loan_payoff(*(money[key] for key in INPUTS[family] if key!='currency'))
        else:
            result = cash_flow(*(money[key] for key in INPUTS[family] if key!='currency'))
    except ScenarioError as exc:
        return refusal(tool,exc.tag,scenario_request(exc.tag,family))
    receipt['modeled_inputs'] = copy.deepcopy(result['modeled_inputs'])
    if observed:
        receipt['carry_forward_hypothetical']=True
        receipt['claim_date_separate_from_scenario_start']=True
        receipt['recorded_start']={'account_id':parameters['account_phrase'],'raw_observed':observed['value'],
            'measurement_view':observed['measurement_view'],
            'modeled_cents':result['modeled_inputs'][start_name], 'quantity':observed['quantity'],'kind':observed['kind'],
            'currency':observed['currency'],'dated':observed['dated'],'grade':observed['grade'],
            'record_ids':copy.deepcopy(observed['record_ids']),'origin':'same_run_accepted_measurement',
            'claim_date_separate_from_scenario_start':True}
    exact_numeric = {}
    for name,value in parameters.items():
        if name not in MONEY_ROLES and name not in {'months','one_off_month','nominal_annual_rate_percent'}: continue
        exact_numeric[name]={'role':MONEY_ROLES.get(name,{'months':'horizon','one_off_month':'one-off at month','nominal_annual_rate_percent':'nominal annual rate'}.get(name)),
                             'raw':value,'origin':'current_question','quote':args['parameter_sources'][name]['quote']}
        if name in MONEY_ROLES: exact_numeric[name].update(currency=parameters['currency'],modeled_cents=result['modeled_inputs'][name])
        else: exact_numeric[name]['unit']={'months':'months','one_off_month':'one_based_modeled_month','nominal_annual_rate_percent':'nominal_annual_percent'}[name]
    receipt['exact_numeric_inputs']=exact_numeric
    stock_boundary = bounded(whole=False)
    flow_boundary = bounded(whole=False,selected=[{'kind':'period','value':parameters['start_date'],'to':result['horizon_date']}])
    out = []
    def emit(key,label,kind,dated='',flow=False):
        out.append(figure(result[key],label,quantity=kind,kind=HYPOTHETICAL,
                          currency='' if kind==quantity.COUNT else parameters['currency'],dated=dated,
                          record_ids=sources,boundary=flow_boundary if flow else stock_boundary))
    end = result['horizon_date']
    if family=='savings_scenario':
        emit('final_balance','hypothetical final savings balance — '+end,quantity.BALANCE,end)
        emit('contributed_principal','hypothetical contributed principal — '+end,quantity.BALANCE,end)
        emit('growth','hypothetical accumulated savings growth',quantity.NET_MOVEMENT,flow=True)
    elif family=='loan_payoff_scenario':
        emit('remaining_debt','hypothetical remaining debt — '+end,quantity.OWED,end)
        emit('interest_paid','hypothetical interest component of simulated repayments',quantity.REPAYMENT,flow=True)
        emit('repayments_paid','hypothetical applied repayments',quantity.REPAYMENT,flow=True)
        emit('payment_count','positive simulated payment count — '+end,quantity.COUNT,end)
    else:
        emit('final_cash','hypothetical final cash — '+end,quantity.BALANCE,end)
        emit('minimum_cash','hypothetical lowest endpoint cash — '+result['minimum_date'],quantity.BALANCE,result['minimum_date'])
    caveats = ['This is a hypothetical monthly scenario, not a bank calculation or spending permission. Money is normalized once to cents; monthly interest and endpoints use half-even rounding. Dates retain the original monthly anchor and clamp to each target month end.']
    if family=='loan_payoff_scenario':
        caveats.append('The starting date is the first payment date; one full modeled monthly interest period precedes that payment. No daily accrual, fees or lender-specific allocation is modeled.')
        if result['payoff_date']: caveats.append('Hypothetical payoff date: '+result['payoff_date']+'.')
        else: caveats.append('No positive-opening debt payoff date is established within this horizon.')
    else:
        caveats.append('The starting date is the opening date; contributions and cash flows occur at anchored monthly endpoints, beginning one month later.')
    if family!='cash_flow_scenario': caveats.append('The rate is nominal annual percent divided by twelve; it is not APY or effective yield. Fees, tax, inflation and market returns are not inferred.')
    else:
        caveats.append('Only monthly endpoint cash is modeled; within-period shortfalls are not measured.')
        if result['first_negative_date']: caveats.append('First hypothetical negative endpoint: '+result['first_negative_date']+'.')
    if observed: caveats.append('Recorded starting value measured '+observed['dated']+' is carried to the scenario anchor hypothetically; its source grade is retained separately in the input receipt.')
    if result['trajectory_sampled']: caveats.append('The trajectory is sampled to at most 24 rows; final, minimum and payoff landmarks are retained.')
    complete = ToolResult(tool=tool,ok=True,data={'view':family,**result,'assumption_receipt':receipt},figures=out,record_ids=sources,caveats=caveats,text='Hypothetical scenario under the explicitly stated assumptions.')
    if len(json.dumps(complete.to_dict()).encode()) > 10_000:
        return refusal(tool,'scenario_payload_limit',scenario_request('scenario_payload_limit',family))
    return complete
